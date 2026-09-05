"""Isolated tests for one-use, cross-worker wallet/plans sign-in."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
from threading import local

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from modstore_server import browser_handoff as service
from modstore_server import browser_handoff_api as routes
from modstore_server.api.csrf import CSRFMiddleware
from modstore_server.api.deps import get_current_user
from modstore_server.db.identity import BrowserHandoffCode, User


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'codes.sqlite'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    User.__table__.create(engine)
    BrowserHandoffCode.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service, "get_session_factory", lambda: factory)
    with factory() as session:
        session.add_all(
            [
                User(
                    id=i,
                    username=f"user-{i}",
                    password_hash=f"password-{i}",
                    account_state="active",
                )
                for i in (1, 2)
            ]
        )
        session.commit()
    yield factory, url
    engine.dispose()


def test_bound_identity_digest_storage_and_replay(database):
    factory, _ = database
    issued = service.issue_code(1, "/wallet?source=fhd&recharge=30", "wallet")
    with factory() as session:
        row = session.query(BrowserHandoffCode).one()
        assert row.code_hash == sha256(issued["code"].encode()).hexdigest()
        assert row.user_id == 1
        assert issued["code"] not in str(row.__dict__)
    user = service.consume_code(issued["code"], "/wallet?recharge=30&source=fhd", "wallet")
    assert user.id == 1
    with pytest.raises(ValueError):
        service.consume_code(issued["code"], issued["target"], "wallet")


def test_independent_workers_can_only_redeem_once(database, monkeypatch):
    _, url = database
    issued = service.issue_code(1, "/plans?plan=svip1", "plans")
    state = local()
    monkeypatch.setattr(service, "get_session_factory", lambda: state.factory)

    def worker(_):
        # Separate engines and sessions, as in independent processes/workers.
        engine = create_engine(url, connect_args={"timeout": 15})
        state.factory = sessionmaker(bind=engine)
        try:
            try:
                return service.consume_code(issued["code"], issued["target"], "plans").id
            except ValueError:
                return None
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(worker, range(8)))
    assert outcomes.count(1) == 1
    assert outcomes.count(None) == 7


@pytest.mark.parametrize(
    "target,purpose",
    [
        ("https://evil.example/wallet", "wallet"),
        ("//evil.example/wallet", "wallet"),
        ("/wallet#xcagi_mt=jwt", "wallet"),
        ("/admin", "wallet"),
        ("/plans", "wallet"),
        ("/wallet?xcagi_mt=jwt", "wallet"),
        ("/wallet?user_id=2", "wallet"),
        ("/wallet?redirect=https://evil.example", "wallet"),
        ("/wallet?recharge=30&recharge=100", "wallet"),
        ("/wallet?recharge=-1", "wallet"),
        ("/plans?plan=a%0Aheader", "plans"),
        ("/wallet", "admin"),
    ],
)
def test_disallowed_targets(database, target, purpose):
    with pytest.raises(ValueError):
        service.issue_code(1, target, purpose)


def test_expired_wrong_purpose_wrong_target_and_changed_credentials(database):
    factory, _ = database
    code = service.issue_code(1, "/wallet?recharge=30", "wallet")["code"]
    for target, purpose in [("/plans", "plans"), ("/wallet?recharge=100", "wallet")]:
        with pytest.raises(ValueError):
            service.consume_code(code, target, purpose)
    with factory() as session:
        session.execute(
            update(BrowserHandoffCode).values(expires_at=datetime.utcnow() - timedelta(seconds=1))
        )
        session.commit()
    with pytest.raises(ValueError):
        service.consume_code(code, "/wallet?recharge=30", "wallet")
    issued = service.issue_code(1, "/wallet", "wallet")
    with factory() as session:
        session.get(User, 1).password_hash = "changed-password"
        session.commit()
    with pytest.raises(ValueError):
        service.consume_code(issued["code"], "/wallet", "wallet")


def test_api_authentication_no_store_user_binding_and_csrf_first_visit(database, monkeypatch):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    from modstore_server.api.app_factory_part01 import _include_router_without_method_conflicts
    from modstore_server.market_auth_api import router as market_auth_router

    app = FastAPI()
    _include_router_without_method_conflicts(app, market_auth_router, prefix="/api")
    paths = app.openapi()["paths"]
    assert "/api/auth/browser-handoff" in paths
    assert "/api/auth/browser-handoff/consume" in paths
    assert "/api/api/auth/browser-handoff" not in paths
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        denied = client.post(
            "/api/auth/browser-handoff",
            headers={"Authorization": "Bearer invalid"},
            json={"target": "/wallet", "purpose": "wallet"},
        )
        assert denied.status_code == 401
        app.dependency_overrides[get_current_user] = lambda: User(id=1)
        issued = client.post(
            "/api/auth/browser-handoff",
            headers={"Authorization": "Bearer valid"},
            json={"target": "/plans?plan=vip", "purpose": "plans"},
        )
        assert issued.status_code == 200
        assert issued.headers["cache-control"] == "no-store"
        rejected = client.post(
            "/api/auth/browser-handoff",
            headers={"Authorization": "Bearer valid"},
            json={"target": "/wallet", "purpose": "wallet", "user_id": 2},
        )
        assert rejected.status_code == 422
        monkeypatch.setattr(
            routes,
            "create_access_token",
            lambda user_id, username, **kw: f"access-user-{user_id}",
        )
        monkeypatch.setattr(
            routes,
            "create_refresh_token",
            lambda user_id, username: f"refresh-user-{user_id}",
        )
        data = issued.json()["data"]
        consumed = client.post(
            "/api/auth/browser-handoff/consume",
            json={k: data[k] for k in ("code", "target", "purpose")},
        )
        assert consumed.status_code == 200
        assert consumed.json()["access_token"] == "access-user-1"
        assert consumed.headers["cache-control"] == "no-store"
        replay = client.post(
            "/api/auth/browser-handoff/consume",
            json={k: data[k] for k in ("code", "target", "purpose")},
        )
        assert replay.status_code == 401


def test_disabled_identity_cannot_issue_or_redeem(database):
    factory, _ = database
    issued = service.issue_code(1, "/wallet", "wallet")
    with factory() as session:
        session.get(User, 1).account_state = "disabled"
        session.commit()
    with pytest.raises(ValueError):
        service.issue_code(1, "/wallet", "wallet")
    with pytest.raises(ValueError):
        service.consume_code(issued["code"], "/wallet", "wallet")


def test_migration_creates_ticket_table_and_index(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    from sqlalchemy import inspect

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260905_browser_handoff.py"
    spec = importlib.util.spec_from_file_location("handoff_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        User.__table__.create(connection)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert "browser_handoff_codes" in inspect(connection).get_table_names()
        assert inspect(connection).get_indexes("browser_handoff_codes")[0]["column_names"] == [
            "expires_at"
        ]
    engine.dispose()
