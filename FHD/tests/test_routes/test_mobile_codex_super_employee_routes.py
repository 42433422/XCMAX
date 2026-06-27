from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.responses import JSONResponse

from app.utils.mobile_api import format_mobile_response


@pytest.fixture
def ext_mod():
    from app.fastapi_routes import (
        mobile_api,  # noqa: F401
        mobile_api_extensions,
    )

    return mobile_api_extensions


@pytest.mark.asyncio
async def test_mobile_admin_codex_messages_lists_user_scoped_messages(ext_mod):
    seen: dict[str, object] = {}

    class FakeCodexService:
        def list_messages(self, *, user_id: int, limit: int = 80):
            seen["user_id"] = user_id
            seen["limit"] = limit
            return [{"id": "m1", "role": "assistant", "body": "ready"}]

    with (
        patch.object(ext_mod, "_require_mobile_admin", return_value=({}, None)),
        patch.object(ext_mod, "CodexSuperEmployeeService", return_value=FakeCodexService()),
    ):
        response = await ext_mod.mobile_admin_codex_super_employee_messages(
            SimpleNamespace(headers={}),
            limit=5,
            user=SimpleNamespace(id=7),
        )

    assert response["success"] is True
    assert response["data"]["messages"][0]["id"] == "m1"
    assert seen == {"user_id": 7, "limit": 5}


@pytest.mark.asyncio
async def test_mobile_admin_codex_messages_uses_bearer_user_id_when_user_is_detached(ext_mod):
    seen: dict[str, object] = {}

    class DetachedUser:
        @property
        def id(self):
            raise RuntimeError("detached")

    class FakeCodexService:
        def list_messages(self, *, user_id: int, limit: int = 80):
            seen["user_id"] = user_id
            return []

    request = SimpleNamespace(headers={"Authorization": "Bearer token-1"})
    with (
        patch.object(ext_mod, "_require_mobile_admin", return_value=({}, None)),
        patch("app.security.mobile_jwt.user_id_from_mobile_bearer", return_value=11),
        patch.object(ext_mod, "CodexSuperEmployeeService", return_value=FakeCodexService()),
    ):
        response = await ext_mod.mobile_admin_codex_super_employee_messages(
            request,
            limit=5,
            user=DetachedUser(),
        )

    assert response["success"] is True
    assert seen["user_id"] == 11


@pytest.mark.asyncio
async def test_mobile_admin_codex_invoke_passes_mobile_context(ext_mod):
    seen: dict[str, object] = {}

    class FakeCodexService:
        def invoke(self, *, user_id: int, message: str, context: dict):
            seen["user_id"] = user_id
            seen["message"] = message
            seen["context"] = context
            return {
                "dispatch": {"request_id": "req-1", "status": "accepted"},
                "messages": [{"id": "m1"}],
            }

    body = ext_mod.CodexSuperEmployeeMobileMessageBody(message="手机派工", context={})
    with (
        patch.object(ext_mod, "_require_mobile_admin", return_value=({}, None)),
        patch.object(ext_mod, "CodexSuperEmployeeService", return_value=FakeCodexService()),
    ):
        response = await ext_mod.mobile_admin_codex_super_employee_invoke(
            SimpleNamespace(headers={}),
            body=body,
            user=SimpleNamespace(id=8),
        )

    assert response["success"] is True
    assert response["data"]["dispatch"]["status"] == "accepted"
    assert seen["user_id"] == 8
    assert seen["message"] == "手机派工"
    assert seen["context"] == {
        "source": "mobile_im",
        "client_surface": "mobile",
        "target_devices": ["all"],
    }


@pytest.mark.asyncio
async def test_mobile_admin_codex_requires_mobile_admin(ext_mod):
    denied = JSONResponse(
        format_mobile_response(None, "需要管理端管理员账号", success=False, code=403),
        status_code=403,
    )
    body = ext_mod.CodexSuperEmployeeMobileMessageBody(message="run")
    with patch.object(ext_mod, "_require_mobile_admin", return_value=({}, denied)):
        response = await ext_mod.mobile_admin_codex_super_employee_invoke(
            SimpleNamespace(headers={}),
            body=body,
            user=SimpleNamespace(id=8),
        )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mobile_admin_codex_invoke_rejects_empty_message(ext_mod):
    class FakeCodexService:
        def invoke(self, *, user_id: int, message: str, context: dict):
            raise ValueError("message 不能为空")

    body = ext_mod.CodexSuperEmployeeMobileMessageBody(message="")
    with (
        patch.object(ext_mod, "_require_mobile_admin", return_value=({}, None)),
        patch.object(ext_mod, "CodexSuperEmployeeService", return_value=FakeCodexService()),
    ):
        response = await ext_mod.mobile_admin_codex_super_employee_invoke(
            SimpleNamespace(headers={}),
            body=body,
            user=SimpleNamespace(id=8),
        )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["message"] == "message 不能为空"
