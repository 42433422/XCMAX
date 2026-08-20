from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.fastapi_routes import internal_im


def _payload(response: JSONResponse) -> dict[str, Any]:
    return json.loads(response.body)


@contextmanager
def _im_runtime(service: MagicMock):
    db = MagicMock()
    with (
        patch.object(internal_im, "ensure_im_tables") as ensure,
        patch.object(internal_im, "get_host_engine", return_value="engine"),
        patch.object(internal_im, "HostSessionLocal", return_value=db),
        patch.object(internal_im, "ImApplicationService", return_value=service),
    ):
        yield db, ensure


def test_mobile_uid_and_internal_key_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    assert internal_im._mobile_uid(SimpleNamespace(id="7")) == 7
    assert internal_im._mobile_uid(SimpleNamespace(id="bad", user_id=8)) == 8
    assert internal_im._mobile_uid(SimpleNamespace(id=-1, user_id=None)) == 0
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_CS_INTAKE_LINK_SECRET", raising=False)
    assert internal_im._internal_api_key() == ""
    monkeypatch.setenv("XCAGI_CS_INTAKE_LINK_SECRET", " fallback ")
    assert internal_im._internal_api_key() == "fallback"
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", " primary ")
    assert internal_im._internal_api_key() == "primary"


@pytest.mark.asyncio
async def test_internal_employee_message_authorization_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = Request({"type": "http", "headers": []})
    unauthorized = await internal_im.internal_employee_message(request, {})
    assert unauthorized.status_code == 401

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "secret")
    request = Request({"type": "http", "headers": [(b"x-internal-api-key", b"secret")]})
    invalid = await internal_im.internal_employee_message(
        request, {"boss_user_id": "bad", "employee_id": "", "body": ""}
    )
    assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_internal_employee_message_persists_and_pushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "secret")
    request = Request({"type": "http", "headers": [(b"x-internal-api-key", b"secret")]})
    service = MagicMock()
    service.post_employee_message.return_value = {
        "conversation_id": 5,
        "message": {"id": 9, "body": "hi"},
        "updated_at_ms": 123,
    }
    hub = SimpleNamespace(send_to_user=AsyncMock())
    with (
        _im_runtime(service) as (db, ensure),
        patch("app.infrastructure.im.ws_hub.im_ws_hub", hub),
    ):
        result = await internal_im.internal_employee_message(
            request,
            {
                "user_id": 7,
                "employee_id": "e1",
                "text": " hi ",
                "display_name": "员工",
            },
        )
    assert result["success"] is True
    ensure.assert_called_once_with("engine")
    db.close.assert_called_once()
    assert hub.send_to_user.await_count == 2


@pytest.mark.asyncio
async def test_internal_employee_message_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "secret")
    request = Request({"type": "http", "headers": [(b"x-internal-api-key", b"secret")]})
    service = MagicMock()
    service.post_employee_message.return_value = {}
    with _im_runtime(service):
        failed = await internal_im.internal_employee_message(
            request, {"boss_user_id": 7, "employee_id": "e", "body": "x"}
        )
    assert failed.status_code == 400

    service.post_employee_message.return_value = {
        "conversation_id": 5,
        "message": {"id": 9},
    }
    hub = SimpleNamespace(send_to_user=AsyncMock(side_effect=RuntimeError("ws down")))
    with _im_runtime(service), patch("app.infrastructure.im.ws_hub.im_ws_hub", hub):
        persisted = await internal_im.internal_employee_message(
            request, {"boss_user_id": 7, "employee_id": "e", "body": "x"}
        )
    assert persisted["success"] is True

    service.post_employee_message.side_effect = RuntimeError("db down")
    with _im_runtime(service):
        errored = await internal_im.internal_employee_message(
            request, {"boss_user_id": 7, "employee_id": "e", "body": "x"}
        )
    assert errored.status_code == 500


def test_list_conversations_authorization_success_and_failure() -> None:
    assert internal_im.im_list_conversations(SimpleNamespace()).status_code == 401
    service = MagicMock()
    service.list_conversations.return_value = [{"id": 1}]
    with _im_runtime(service) as (db, _ensure):
        result = internal_im.im_list_conversations(SimpleNamespace(id=7))
    assert result == {"success": True, "conversations": [{"id": 1}]}
    db.close.assert_called_once()

    service.list_conversations.side_effect = RuntimeError("db down")
    with _im_runtime(service):
        response = internal_im.im_list_conversations(SimpleNamespace(id=7))
    assert response.status_code == 500


def test_create_direct_validation_success_and_errors() -> None:
    assert internal_im.im_create_direct({}, SimpleNamespace()).status_code == 401
    assert internal_im.im_create_direct({}, SimpleNamespace(id=7)).status_code == 400
    service = MagicMock()
    service.get_or_create_direct.return_value = {"id": 3}
    with _im_runtime(service):
        result = internal_im.im_create_direct({"peer_user_id": 8}, SimpleNamespace(id=7))
    assert result["conversation"] == {"id": 3}

    for error, status in ((ValueError("bad"), 400), (RuntimeError("db"), 500)):
        service.get_or_create_direct.side_effect = error
        with _im_runtime(service):
            response = internal_im.im_create_direct({"peer_user_id": 8}, SimpleNamespace(id=7))
        assert response.status_code == status


def test_list_messages_authorization_success_and_errors() -> None:
    assert internal_im.im_list_messages(1, SimpleNamespace()).status_code == 401
    service = MagicMock()
    service.list_messages.return_value = [{"id": 2}]
    with _im_runtime(service):
        result = internal_im.im_list_messages(1, SimpleNamespace(id=7), limit=10)
    assert result["messages"] == [{"id": 2}]
    service.list_messages.assert_called_once_with(1, 7, limit=10)

    for error, status in ((PermissionError(), 403), (RuntimeError("db"), 500)):
        service.list_messages.side_effect = error
        with _im_runtime(service):
            response = internal_im.im_list_messages(1, SimpleNamespace(id=7))
        assert response.status_code == status


def test_post_message_relay_success_no_relay_and_errors() -> None:
    assert internal_im.im_post_message(1, {}, SimpleNamespace()).status_code == 401
    service = MagicMock()
    service.send_message.return_value = {"message": {"id": 1}}
    service.employee_id_for_conversation.return_value = "emp-1"
    with (
        _im_runtime(service),
        patch.object(internal_im, "_relay_employee_answer") as relay,
    ):
        result = internal_im.im_post_message(1, {"body": "answer"}, SimpleNamespace(id=7))
    assert result["success"] is True
    relay.assert_called_once_with(7, "emp-1", "answer")

    service.employee_id_for_conversation.return_value = ""
    with (
        _im_runtime(service),
        patch.object(internal_im, "_relay_employee_answer") as relay,
    ):
        internal_im.im_post_message(1, {}, SimpleNamespace(id=7))
    relay.assert_not_called()

    for error, status in (
        (PermissionError(), 403),
        (ValueError("bad"), 400),
        (RuntimeError("db"), 500),
    ):
        service.send_message.side_effect = error
        with _im_runtime(service):
            response = internal_im.im_post_message(1, {}, SimpleNamespace(id=7))
        assert response.status_code == status


def test_mark_read_default_explicit_success_and_errors() -> None:
    assert internal_im.im_mark_read(1, {}, SimpleNamespace()).status_code == 401
    service = MagicMock()
    service.mark_read.return_value = {"updated": 2}
    with _im_runtime(service):
        result = internal_im.im_mark_read(1, {"last_message_id": "bad"}, SimpleNamespace(id=7))
    assert result["updated"] == 2
    service.mark_read.assert_called_once_with(1, 7, 2_147_483_647)

    service.mark_read.reset_mock()
    with _im_runtime(service):
        internal_im.im_mark_read(1, {"last_message_id": 9}, SimpleNamespace(id=7))
    service.mark_read.assert_called_once_with(1, 7, 9)

    for error, status in ((PermissionError(), 403), (RuntimeError("db"), 500)):
        service.mark_read.side_effect = error
        with _im_runtime(service):
            response = internal_im.im_mark_read(1, {}, SimpleNamespace(id=7))
        assert response.status_code == status
