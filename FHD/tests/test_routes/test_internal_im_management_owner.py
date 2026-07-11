from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from app.fastapi_routes import internal_im


def test_regular_internal_im_recipient_keeps_local_user_id():
    assert internal_im._resolve_management_owner_user_id(9, "") == 9


def test_management_owner_recipient_resolves_local_admin(monkeypatch):
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        id=17,
        tenant_id=8,
    )
    monkeypatch.setattr(internal_im, "HostSessionLocal", lambda: db)

    assert (
        internal_im._resolve_management_owner_user_id(
            9,
            "management_owner",
            "fhd:user:17:tenant:8",
        )
        == 17
    )
    db.close.assert_called_once()


def test_management_owner_resolution_fails_closed_without_local_admin(monkeypatch):
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.first.return_value = None
    monkeypatch.setattr(internal_im, "HostSessionLocal", lambda: db)

    assert (
        internal_im._resolve_management_owner_user_id(
            9,
            "management_owner",
            "fhd:user:17:tenant:8",
        )
        == 0
    )
    db.close.assert_called_once()


def test_management_owner_without_exact_recipient_never_falls_back(monkeypatch):
    monkeypatch.setattr(
        internal_im,
        "HostSessionLocal",
        lambda: pytest.fail("missing recipient_ref must fail before DB access"),
    )
    assert internal_im._resolve_management_owner_user_id(9, "management_owner") == 0
    assert (
        internal_im._resolve_management_owner_user_id(
            9,
            "management_owner",
            "fhd:user:17:tenant:8:extra",
        )
        == 0
    )


def test_management_owner_tenant_change_invalidates_recipient_ref(monkeypatch):
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        id=17,
        tenant_id=9,
    )
    monkeypatch.setattr(internal_im, "HostSessionLocal", lambda: db)

    assert (
        internal_im._resolve_management_owner_user_id(
            9,
            "management_owner",
            "fhd:user:17:tenant:8",
        )
        == 0
    )
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_internal_message_rejects_bad_key_before_any_im_write(monkeypatch):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/internal/im/employee-message",
            "headers": [(b"x-internal-api-key", b"wrong-key")],
        }
    )
    monkeypatch.setattr(internal_im, "_internal_api_key", lambda: "shared-key")
    monkeypatch.setattr(
        internal_im,
        "ensure_im_tables",
        lambda *_args: pytest.fail("unauthorized calls must not touch IM storage"),
    )
    monkeypatch.setattr(
        internal_im,
        "ImApplicationService",
        lambda *_args: pytest.fail("unauthorized calls must not create an IM message"),
    )

    result = await internal_im.internal_employee_message(
        request,
        {
            "boss_user_id": 7,
            "employee_id": "intent-analyst",
            "body": "must not be stored",
        },
    )

    assert result.status_code == 401


@pytest.mark.asyncio
async def test_management_notification_skips_ordinary_im_and_shared_websocket(monkeypatch):
    import app.services.mobile_push as mobile_push
    from app.infrastructure.im.ws_hub import im_ws_hub

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/internal/im/employee-message",
            "headers": [(b"x-internal-api-key", b"shared-key")],
        }
    )
    seen = {}

    def fake_notify(user_id, title, body, data, **kwargs):
        seen.update(
            user_id=user_id,
            title=title,
            body=body,
            data=data,
            kwargs=kwargs,
        )
        return {"fcm": False, "outbox": True}

    monkeypatch.setattr(internal_im, "_internal_api_key", lambda: "shared-key")
    monkeypatch.setattr(
        internal_im,
        "_resolve_management_owner_principal",
        lambda *_args: (7, 8),
    )
    monkeypatch.setattr(
        internal_im,
        "ensure_im_tables",
        lambda *_args: pytest.fail("management content must not enter ordinary IM"),
    )
    monkeypatch.setattr(
        internal_im,
        "ImApplicationService",
        lambda *_args: pytest.fail("management content must not create an IM message"),
    )
    ws_send = AsyncMock()
    monkeypatch.setattr(im_ws_hub, "send_to_user", ws_send)
    monkeypatch.setattr(mobile_push, "notify_user", fake_notify)

    result = await internal_im.internal_employee_message(
        request,
        {
            "boss_user_id": 9,
            "employee_id": "intent-analyst",
            "body": "管理任务等待验收",
            "notification": {
                "title": "员工已交付",
                "task_id": "mwi_1",
                "recipient_kind": "management_owner",
                "recipient_ref": "fhd:user:7:tenant:8",
            },
        },
    )

    assert result["success"] is True
    assert result["delivery_channel"] == "management_outbox"
    assert seen["user_id"] == 7
    assert seen["kwargs"] == {"audience": "management", "tenant_id": 8}
    assert seen["data"]["recipient_kind"] == "management_owner"
    assert seen["data"]["recipient_ref"] == "fhd:user:7:tenant:8"
    ws_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_regular_employee_message_keeps_ordinary_im_and_websocket(monkeypatch):
    from app.infrastructure.im.ws_hub import im_ws_hub

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/internal/im/employee-message",
            "headers": [(b"x-internal-api-key", b"shared-key")],
        }
    )
    seen = {}

    class FakeDb:
        def close(self):
            seen["closed"] = True

    class FakeImService:
        def __init__(self, _db):
            pass

        def post_employee_message(self, **kwargs):
            seen["post"] = kwargs
            return {
                "conversation_id": 12,
                "message": {"id": 34, "body": kwargs["body"]},
                "updated_at_ms": 123,
            }

    monkeypatch.setattr(internal_im, "_internal_api_key", lambda: "shared-key")
    monkeypatch.setattr(internal_im, "ensure_im_tables", lambda *_args: None)
    monkeypatch.setattr(internal_im, "get_host_engine", lambda: object())
    monkeypatch.setattr(internal_im, "HostSessionLocal", FakeDb)
    monkeypatch.setattr(internal_im, "ImApplicationService", FakeImService)
    ws_send = AsyncMock()
    monkeypatch.setattr(im_ws_hub, "send_to_user", ws_send)

    result = await internal_im.internal_employee_message(
        request,
        {
            "boss_user_id": 7,
            "employee_id": "support-agent",
            "body": "普通员工消息",
        },
    )

    assert result["success"] is True
    assert result["conversation_id"] == 12
    assert seen["post"]["boss_user_id"] == 7
    assert seen["closed"] is True
    assert ws_send.await_count == 2


def test_internal_modstore_candidates_drop_public_and_credentialed_urls(monkeypatch):
    monkeypatch.setenv("XCAGI_MODSTORE_INTERNAL_URL", "https://xiu-ci.com")
    monkeypatch.setenv("MODSTORE_INTERNAL_BASE_URL", "http://10.20.30.40:8788")
    monkeypatch.setenv("MODSTORE_PLATFORM_URL", "http://user:pass@127.0.0.1:8788")
    monkeypatch.setenv("MODSTORE_LOCAL_BASE_URL", "http://192.168.10.2:8788")

    candidates = internal_im._modstore_internal_candidates()
    assert "https://xiu-ci.com" not in candidates
    assert "http://user:pass@127.0.0.1:8788" not in candidates
    assert "http://10.20.30.40:8788" in candidates
    assert "http://192.168.10.2:8788" in candidates


def test_internal_im_key_uses_only_modstore_key_names(monkeypatch):
    import app.security.local_runtime_secret as secret_module

    seen = []

    def fake_secret(*keys):
        seen.extend(keys)
        return "shared-key"

    monkeypatch.setattr(secret_module, "local_runtime_secret", fake_secret)
    assert internal_im._internal_api_key() == "shared-key"
    assert seen == ["MODSTORE_INTERNAL_API_KEY", "XCAGI_MARKET_INTERNAL_API_KEY"]
