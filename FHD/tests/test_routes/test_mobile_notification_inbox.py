from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.models.mobile_notification import MobileNotificationOutbox
from app.db.models.user import User
from app.fastapi_routes.mobile_extensions.routes_devices import DeviceRoutes, DeviceRoutesPorts


def test_notification_read_is_independent_of_delivery_and_scoped(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    principal = User(id=7, tenant_id=2, is_active=True, username="owner", password="unused")
    now = datetime(2026, 11, 25, 12)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        scripts.get_revision("2026_06_25_mobile_outbox").module.upgrade()
        connection.execute(
            text(
                "INSERT INTO mobile_notification_outbox (id, user_id, title, delivered, created_at) "
                "VALUES (4, 7, 'unbound legacy', true, :created_at)"
            ),
            {"created_at": now.isoformat(sep=" ")},
        )
        scripts.get_revision("2026_11_25_notification_read").module.upgrade()

    @contextmanager
    def database():
        with Session(engine) as db, db.begin():
            yield db

    with database() as db:
        db.add_all(
            [
                MobileNotificationOutbox(
                    id=1, user_id=7, recipient_scope="tenant:2", title="original", delivered=True
                ),
                MobileNotificationOutbox(
                    id=2, user_id=7, recipient_scope="tenant:3", title="other tenant"
                ),
                MobileNotificationOutbox(
                    id=3, user_id=8, recipient_scope="tenant:2", title="other user"
                ),
                MobileNotificationOutbox(
                    id=5, user_id=7, recipient_scope="tenant:2", title="undelivered"
                ),
            ]
        )

    async def get_user():
        return principal

    app = FastAPI()
    ports = DeviceRoutesPorts(
        database=database,
        warning=lambda *_: None,
        ensure_mobile_device_table=lambda: None,
        now=lambda: now,
        ensure_outbox_table=lambda: None,
    )
    app.include_router(DeviceRoutes(ports, get_user).router)
    desktop = TestClient(app)
    mobile = TestClient(app)
    first = desktop.get("/notifications/inbox?limit=1").json()["data"]
    assert [item["id"] for item in first["notifications"]] == [5]
    assert first["notifications"][0]["is_read"] is False
    assert first["next_before_id"] == 5
    second = desktop.get("/notifications/inbox?before_id=5").json()["data"]
    assert [item["id"] for item in second["notifications"]] == [1]
    assert second["notifications"][0]["is_read"] is False
    assert mobile.post("/notifications/2/read").status_code == 404
    assert mobile.post("/notifications/3/read").status_code == 404
    assert mobile.post("/notifications/4/read").status_code == 404
    receipt = mobile.post("/notifications/5/read").json()["data"]
    assert receipt["is_read"] is True
    now += timedelta(seconds=10)
    assert desktop.post("/notifications/5/read").json()["data"] == receipt
    assert desktop.get("/notifications/inbox").json()["data"]["notifications"][0] == receipt
    with database() as db:
        assert db.get(MobileNotificationOutbox, 5).delivered is False
        assert db.get(MobileNotificationOutbox, 1).read_at is None
        historical = db.get(MobileNotificationOutbox, 4)
        assert (
            historical.title,
            historical.delivered,
            historical.recipient_scope,
            historical.read_at,
        ) == ("unbound legacy", True, "", None)
    principal = SimpleNamespace(id=7, tenant_id=2, is_active=True)
    assert desktop.get("/notifications/inbox").status_code == 401
    engine.dispose()
