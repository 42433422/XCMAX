"""Release-gate regressions for public error responses."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mobile_routes():
    from app.fastapi_routes import (
        mobile_api,  # noqa: F401
        mobile_api_extensions,
    )

    return mobile_api_extensions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "service_name"),
    [
        ("mobile_admin_codex_super_employee_messages", "CodexSuperEmployeeService"),
        ("mobile_admin_claude_super_employee_messages", "ClaudeSuperEmployeeService"),
        ("mobile_admin_cursor_super_employee_messages", "CursorSuperEmployeeService"),
        ("mobile_admin_trae_super_employee_messages", "TraeSuperEmployeeService"),
    ],
)
async def test_super_employee_message_routes_hide_internal_errors(
    mobile_routes, route_name: str, service_name: str
) -> None:
    secret = "secret database path /private/customer.db"
    service = MagicMock()
    service.list_messages.side_effect = RuntimeError(secret)

    with (
        patch.object(
            mobile_routes,
            "_require_mobile_admin_or_enterprise",
            return_value=({}, None),
        ),
        patch.object(mobile_routes, "_mobile_request_user_id", return_value=7),
        patch.object(mobile_routes, service_name, return_value=service),
    ):
        response = await getattr(mobile_routes, route_name)(
            request=MagicMock(), limit=80, user=SimpleNamespace(id=7)
        )

    payload = json.loads(response.body)
    assert response.status_code == 500
    assert payload["message"] == "超级员工消息暂时不可用，请稍后重试"
    assert secret not in response.body.decode("utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "service_name"),
    [
        ("mobile_admin_codex_super_employee_invoke", "CodexSuperEmployeeService"),
        ("mobile_admin_claude_super_employee_invoke", "ClaudeSuperEmployeeService"),
        ("mobile_admin_cursor_super_employee_invoke", "CursorSuperEmployeeService"),
        ("mobile_admin_trae_super_employee_invoke", "TraeSuperEmployeeService"),
    ],
)
async def test_super_employee_invoke_routes_hide_internal_errors(
    mobile_routes, route_name: str, service_name: str
) -> None:
    secret = "secret token and stack frame"
    service = MagicMock()
    service.invoke.side_effect = RuntimeError(secret)
    body = SimpleNamespace(message="执行任务", body="", context={}, workspace_id="")

    with (
        patch.object(
            mobile_routes,
            "_require_mobile_admin_or_enterprise",
            return_value=({}, None),
        ),
        patch.object(mobile_routes, "_mobile_request_user_id", return_value=7),
        patch.object(mobile_routes, "_mobile_session_meta", return_value={}),
        patch.object(mobile_routes, service_name, return_value=service),
    ):
        response = await getattr(mobile_routes, route_name)(
            request=MagicMock(), body=body, user=SimpleNamespace(id=7)
        )

    payload = json.loads(response.body)
    assert response.status_code == 500
    assert payload["message"] == "超级员工暂时不可用，请稍后重试"
    assert secret not in response.body.decode("utf-8")


@pytest.mark.asyncio
async def test_super_employee_invoke_keeps_actionable_empty_message_error(mobile_routes) -> None:
    body = SimpleNamespace(message="", body="", context={}, workspace_id="")
    with (
        patch.object(
            mobile_routes,
            "_require_mobile_admin_or_enterprise",
            return_value=({}, None),
        ),
        patch.object(mobile_routes, "_mobile_request_user_id", return_value=7),
    ):
        response = await mobile_routes.mobile_admin_codex_super_employee_invoke(
            request=MagicMock(), body=body, user=SimpleNamespace(id=7)
        )

    payload = json.loads(response.body)
    assert response.status_code == 400
    assert payload["message"] == "message 不能为空"
