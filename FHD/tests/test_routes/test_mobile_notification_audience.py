from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import app.db.session as session_module
from app.db.models.mobile_device import MobileDeviceToken
from app.db.models.mobile_notification import MobileNotificationOutbox
from app.db.models.user import User
from app.services.mobile_push import (
    enqueue_outbox,
    ensure_mobile_notification_schema,
    notification_scope_for_user,
    notify_user,
)


@pytest.fixture(scope="module")
def mobile_ext():
    from app.fastapi_routes import (
        mobile_api,  # noqa: F401
        mobile_api_extensions,
    )

    return mobile_api_extensions


@pytest.fixture
def notification_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    MobileDeviceToken.__table__.create(engine)
    MobileNotificationOutbox.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            User(
                id=7,
                username="notification-owner",
                password="!",
                role="admin",
                is_active=True,
                tenant_id=8,
            )
        )
        db.commit()

    @contextmanager
    def fake_get_db():
        db = factory()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr(session_module, "get_db", fake_get_db)
    return fake_get_db


def _principal(*, role: str, token_scope: str = "", tenant_id: int | None = 8):
    return SimpleNamespace(
        id=7,
        role=role,
        tier=role,
        token_scope=token_scope,
        tenant_id=tenant_id,
        is_active=True,
    )


def test_notification_scope_is_server_derived() -> None:
    management = _principal(role="admin", token_scope="management_pairing")
    enterprise = _principal(role="enterprise", token_scope="enterprise_pairing")
    enterprise.product_sku = "management"

    assert notification_scope_for_user(management) == ("management", 8)
    assert notification_scope_for_user(enterprise) == ("enterprise", 8)
    assert notification_scope_for_user(_principal(role="enterprise", tenant_id=None)) == (
        "enterprise",
        0,
    )
    assert notification_scope_for_user(
        _principal(role="admin", token_scope="management_pairing", tenant_id=None)
    ) == ("management", 0)


def test_runtime_schema_upgrade_survives_caller_rollback() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, tenant_id INTEGER)"))
        connection.execute(text("INSERT INTO users(id, tenant_id) VALUES (7, 88)"))
        connection.execute(
            text(
                "CREATE TABLE mobile_device_tokens ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, fcm_token TEXT NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO mobile_device_tokens(id, user_id, fcm_token) VALUES (1, 7, 'old')")
        )
        connection.execute(
            text(
                "CREATE TABLE mobile_notification_outbox ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO mobile_notification_outbox(id, user_id) VALUES (1, 7)")
        )
    factory = sessionmaker(bind=engine)
    with factory() as db:
        ensure_mobile_notification_schema(db)
        db.rollback()

    inspector = inspect(engine)
    for table in ("mobile_device_tokens", "mobile_notification_outbox"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert {"notification_audience", "tenant_id"} <= columns
        with engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT notification_audience, tenant_id FROM {table}")
            ).one()
        assert row == ("enterprise", 88)


def test_runtime_schema_upgrade_handles_users_without_tenant_column() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO users(id) VALUES (7)"))
        connection.execute(
            text(
                "CREATE TABLE mobile_device_tokens ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, fcm_token TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE mobile_notification_outbox ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL)"
            )
        )
    factory = sessionmaker(bind=engine)
    with factory() as db:
        ensure_mobile_notification_schema(db)
        db.commit()

    with engine.connect() as connection:
        for table in ("mobile_device_tokens", "mobile_notification_outbox"):
            columns = {column["name"] for column in inspect(engine).get_columns(table)}
            assert {"notification_audience", "tenant_id"} <= columns
            assert connection.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL")
            ).scalar_one() == 0


def test_database_defaults_keep_rolling_upgrade_writers_compatible() -> None:
    engine = create_engine("sqlite:///:memory:")
    MobileDeviceToken.__table__.create(engine)
    MobileNotificationOutbox.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO mobile_device_tokens "
                "(user_id, fcm_token, push_provider, push_token, product_sku, "
                "platform, device_label, updated_at) "
                "VALUES (7, 'legacy', 'fcm', 'legacy', 'enterprise', "
                "'android', 'old writer', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO mobile_notification_outbox "
                "(user_id, title, body, route, channel, data_json, delivered, created_at) "
                "VALUES (7, 'legacy', 'body', '', '', '{}', 0, CURRENT_TIMESTAMP)"
            )
        )
        device_scope = connection.execute(
            text(
                "SELECT notification_audience, tenant_id "
                "FROM mobile_device_tokens"
            )
        ).one()
        outbox_scope = connection.execute(
            text(
                "SELECT notification_audience, tenant_id "
                "FROM mobile_notification_outbox"
            )
        ).one()
    assert device_scope == ("enterprise", 0)
    assert outbox_scope == ("enterprise", 0)


@pytest.mark.asyncio
async def test_device_registration_ignores_client_sku_for_authorization(
    mobile_ext,
    notification_db,
) -> None:
    body = mobile_ext.DeviceRegisterBody(
        fcm_token="shared-phone-token",
        push_token="shared-phone-token",
        product_sku="management",
    )
    enterprise_user = _principal(role="enterprise", token_scope="enterprise_pairing")
    await mobile_ext.mobile_device_register(body=body, user=enterprise_user)
    with notification_db() as db:
        row = db.query(MobileDeviceToken).one()
        assert row.notification_audience == "enterprise"
        assert row.tenant_id == 8

    management_user = _principal(role="admin", token_scope="management_pairing")
    await mobile_ext.mobile_device_register(body=body, user=management_user)
    with notification_db() as db:
        row = db.query(MobileDeviceToken).one()
        assert row.notification_audience == "management"
        assert row.tenant_id == 8


@pytest.mark.asyncio
async def test_pending_and_ack_are_partitioned_by_audience(
    mobile_ext,
    notification_db,
) -> None:
    payload = {"event_id": "same-event", "route": "management_work/mwi_1"}
    assert enqueue_outbox(7, "企业消息", "企业正文", payload, tenant_id=8)
    assert enqueue_outbox(
        7,
        "管理消息",
        "管理正文",
        payload,
        audience="management",
        tenant_id=8,
    )

    enterprise_user = _principal(role="enterprise", token_scope="enterprise_pairing")
    management_user = _principal(role="admin", token_scope="management_pairing")
    enterprise_pending = await mobile_ext.mobile_notifications_pending(
        limit=50, user=enterprise_user
    )
    management_pending = await mobile_ext.mobile_notifications_pending(
        limit=50, user=management_user
    )

    assert [row["title"] for row in enterprise_pending["data"]["notifications"]] == ["企业消息"]
    management_items = management_pending["data"]["notifications"]
    assert [row["title"] for row in management_items] == ["管理消息"]

    denied = await mobile_ext.mobile_notification_ack(
        management_items[0]["id"], user=enterprise_user
    )
    assert denied.status_code == 404
    accepted = await mobile_ext.mobile_notification_ack(
        management_items[0]["id"], user=management_user
    )
    assert accepted["data"]["acked"] is True


@pytest.mark.asyncio
async def test_pending_is_partitioned_by_tenant(mobile_ext, notification_db) -> None:
    assert enqueue_outbox(7, "租户 8", "正文", {"event_id": "tenant-8"}, tenant_id=8)
    assert enqueue_outbox(7, "租户 9", "正文", {"event_id": "tenant-9"}, tenant_id=9)

    pending = await mobile_ext.mobile_notifications_pending(
        limit=50,
        user=_principal(role="enterprise", token_scope="enterprise_pairing", tenant_id=8),
    )
    assert [row["title"] for row in pending["data"]["notifications"]] == ["租户 8"]


@pytest.mark.asyncio
async def test_management_outbox_canonicalizes_global_admin_tenant(
    mobile_ext,
    notification_db,
) -> None:
    assert enqueue_outbox(
        7,
        "全局管理消息",
        "正文",
        {"event_id": "global-management"},
        audience="management",
    )
    principal = _principal(
        role="admin",
        token_scope="management_pairing",
        tenant_id=None,
    )
    pending = await mobile_ext.mobile_notifications_pending(limit=50, user=principal)
    assert [row["title"] for row in pending["data"]["notifications"]] == ["全局管理消息"]


def test_notify_user_sends_only_to_matching_devices(
    monkeypatch,
    notification_db,
) -> None:
    with notification_db() as db:
        db.add_all(
            [
                MobileDeviceToken(
                    user_id=7,
                    fcm_token="enterprise-token",
                    push_token="enterprise-token",
                    notification_audience="enterprise",
                    tenant_id=8,
                ),
                MobileDeviceToken(
                    user_id=7,
                    fcm_token="management-token",
                    push_token="management-token",
                    notification_audience="management",
                    tenant_id=8,
                ),
            ]
        )

    seen: list[str] = []

    def fake_send(devices, _title, _body, _data):
        seen.extend(str(device["push_token"]) for device in devices)
        return {"fcm": True}

    monkeypatch.setattr("app.services.mobile_push.send_to_user_devices", fake_send)
    result = notify_user(
        7,
        "员工已交付",
        "等待验收",
        {"event_id": "management-only"},
        audience="management",
        tenant_id=8,
    )

    assert seen == ["management-token"]
    assert result == {"fcm": True, "outbox": True}


def test_notify_user_resolves_authoritative_tenant_and_deduplicates_before_fcm(
    monkeypatch,
    notification_db,
) -> None:
    with notification_db() as db:
        db.add_all(
            [
                MobileDeviceToken(
                    user_id=7,
                    fcm_token="tenant-8",
                    push_token="tenant-8",
                    notification_audience="enterprise",
                    tenant_id=8,
                ),
                MobileDeviceToken(
                    user_id=7,
                    fcm_token="tenant-9",
                    push_token="tenant-9",
                    notification_audience="enterprise",
                    tenant_id=9,
                ),
            ]
        )

    batches: list[list[str]] = []

    def fake_send(devices, _title, _body, _data):
        batches.append([str(device["push_token"]) for device in devices])
        return {"fcm": True}

    monkeypatch.setattr("app.services.mobile_push.send_to_user_devices", fake_send)
    payload = {"event_id": "tenant-scoped-event"}
    first = notify_user(7, "企业消息", "正文", payload, audience="enterprise")
    second = notify_user(7, "企业消息", "正文", payload, audience="enterprise")

    assert batches == [["tenant-8"]]
    assert first == {"fcm": True, "outbox": True}
    assert second == {"fcm": False, "outbox": True, "deduplicated": True}
    with notification_db() as db:
        rows = db.query(MobileNotificationOutbox).all()
        assert len(rows) == 1
        assert rows[0].tenant_id == 8
        assert rows[0].event_id == "tenant-scoped-event"


def test_notify_user_rejects_invalid_audience_and_tenant(
    monkeypatch,
    notification_db,
) -> None:
    send = monkeypatch.setattr(
        "app.services.mobile_push.send_to_user_devices",
        lambda *_args, **_kwargs: pytest.fail("FCM must not run"),
    )
    assert send is None
    assert notify_user(7, "错误", "正文", audience="managment") == {
        "fcm": False,
        "outbox": False,
    }
    assert notify_user(7, "错误", "正文", audience="enterprise", tenant_id=9) == {
        "fcm": False,
        "outbox": False,
    }
    with notification_db() as db:
        assert db.query(MobileNotificationOutbox).count() == 0


def test_concurrent_enqueue_keeps_one_scoped_event(monkeypatch, tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'notifications.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    MobileDeviceToken.__table__.create(engine)
    MobileNotificationOutbox.__table__.create(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def fake_get_db():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(session_module, "get_db", fake_get_db)
    payload = {"event_id": "one-concurrent-event"}

    def enqueue() -> bool:
        return enqueue_outbox(7, "标题", "正文", payload, tenant_id=8)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: enqueue(), range(16)))

    assert all(results)
    with fake_get_db() as db:
        rows = db.query(MobileNotificationOutbox).all()
        assert len(rows) == 1
        assert rows[0].event_id == "one-concurrent-event"
