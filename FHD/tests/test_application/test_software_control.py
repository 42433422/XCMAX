"""Internal model tool -> workflow -> actor-scoped screen -> verified receipt."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.aiopen.software_control import (
    execute_software_control,
    request_screen_owner,
    screen_actor_scope,
)
from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub


def test_screen_identity_comes_from_validated_session(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda request: SimpleNamespace(id=3, tenant_id=7, is_active=True),
    )
    assert request_screen_owner(object()) == {"owner_id": "3", "tenant_id": "7"}
    assert request_screen_owner(None) == {}


@pytest.mark.parametrize(
    "user",
    [
        None,
        SimpleNamespace(id=3, tenant_id=7, is_active=False),
        SimpleNamespace(id=3, tenant_id=None),
        SimpleNamespace(id=True, tenant_id=7),
        SimpleNamespace(id=3, tenant_id=0),
        SimpleNamespace(id=3, tenant_id=-1),
    ],
)
def test_missing_or_inactive_identity_cannot_own_a_screen(monkeypatch, user):
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user", lambda request: user
    )
    assert request_screen_owner(object()) == {}


def test_model_supplied_identity_is_not_trusted():
    result = execute_software_control(
        "click", {"owner_id": "3", "tenant_id": "7", "selector": "#delete"}, {}, "", ""
    )
    assert result["code"] == "SCREEN_IDENTITY_REQUIRED"
    forged_runtime = execute_software_control(
        "click", {"selector": "#delete"}, {"actor_id": "3", "tenant_id": "7"}, "", ""
    )
    assert forged_runtime["code"] == "SCREEN_IDENTITY_REQUIRED"


def test_screen_contract_allows_clearing_controls_but_requires_field_presence():
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    for action, field, value in [
        ("type", "text", ""),
        ("select", "values", []),
        ("set_files", "file_ids", []),
    ]:
        result = resolve_registered_capability_call(
            {
                "tool_id": "software",
                "action": action,
                "params": {"selector": "#input", field: value},
            }
        )
        assert result["success"] is True, result
        missing = resolve_registered_capability_call(
            {"tool_id": "software", "action": action, "params": {"selector": "#input"}}
        )
        assert missing["success"] is False


@pytest.mark.asyncio
async def test_external_file_tools_require_session_identity(monkeypatch):
    from app.application.aiopen.service import AIOPEN_STATE, invoke_tool
    from app.infrastructure.aiopen.cursor_hub import aiopen_cursor_hub

    monkeypatch.setitem(AIOPEN_STATE, "remote_control_enabled", True)
    dispatch = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(aiopen_cursor_hub, "dispatch", dispatch)
    monkeypatch.setattr(
        "app.application.aiopen.screen_identity.external_screen_identity", lambda: {}
    )
    denied = await invoke_tool("ui_files", {"owner_id": "other", "tenant_id": "8"}, None)
    assert denied["code"] == "SCREEN_IDENTITY_REQUIRED"
    dispatch.assert_not_called()
    monkeypatch.setattr(
        "app.application.aiopen.screen_identity.external_screen_identity",
        lambda: {"owner_id": "3", "tenant_id": "7"},
    )
    await invoke_tool(
        "ui_set_files", {"selector": "#file", "file_ids": ["selected"], "owner_id": "other"}, None
    )
    assert dispatch.call_args.kwargs["owner_id"] == "3"
    assert dispatch.call_args.kwargs["tenant_id"] == "7"


@pytest.mark.asyncio
async def test_real_model_workflow_dispatch_reaches_owned_screen(monkeypatch):
    from app.application.tools.workflow import execute_workflow_tool

    hub = AiOpenCursorHub()
    commands = []

    async def acknowledge(raw):
        command = json.loads(raw)
        commands.append(command)
        hub.handle_client_message(
            json.dumps(
                {
                    "type": "result",
                    "id": command["id"],
                    "result": {"success": True, "route": "/customers", "elements": []},
                }
            ),
            session_id="owner-screen",
        )

    screen = AsyncMock()
    screen.send_text.side_effect = acknowledge
    await hub.connect("owner-screen", screen, {"owner_id": "3", "tenant_id": "7"})
    monkeypatch.setattr("app.infrastructure.aiopen.cursor_hub.aiopen_cursor_hub", hub)
    monkeypatch.setattr(
        "app.application.aiopen.software_control.request_screen_owner",
        lambda request: {"owner_id": "3", "tenant_id": "7"},
    )
    result = await asyncio.to_thread(
        execute_workflow_tool,
        "execute_erp_capability",
        {"tool_id": "software", "action": "snapshot", "params": {"session_id": "owner-screen"}},
    )
    payload = json.loads(result)
    assert payload["success"] is True, payload
    assert payload["result"]["route"] == "/customers"
    assert commands[0]["action"] == "snapshot"


@pytest.mark.asyncio
async def test_software_cannot_list_or_dispatch_another_users_screen(monkeypatch):
    hub = AiOpenCursorHub()
    screen = AsyncMock()
    await hub.connect("other", screen, {"owner_id": "9", "tenant_id": "7"})
    monkeypatch.setattr("app.infrastructure.aiopen.cursor_hub.aiopen_cursor_hub", hub)
    context = {"actor_id": "3", "tenant_id": "7"}
    with screen_actor_scope(context):
        listing = execute_software_control("list", {}, context, "", "")
    assert listing["sessions"] == []
    with screen_actor_scope(context):
        result = await asyncio.to_thread(
            execute_software_control,
            "click",
            {"session_id": "other", "selector": "#delete"},
            context,
            "",
            "",
        )
    assert result["code"] == "SCREEN_NOT_OWNED"
    screen.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_software_cannot_cross_tenants_even_for_same_actor(monkeypatch):
    hub = AiOpenCursorHub()
    screen = AsyncMock()
    await hub.connect("other", screen, {"owner_id": "3", "tenant_id": "99"})
    monkeypatch.setattr("app.infrastructure.aiopen.cursor_hub.aiopen_cursor_hub", hub)
    with screen_actor_scope({"actor_id": "3", "tenant_id": "7"}):
        result = await asyncio.to_thread(
            execute_software_control,
            "snapshot",
            {"session_id": "other"},
            {},
            "",
            "",
        )
    assert result["code"] == "SCREEN_NOT_OWNED"
    screen.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_expired_screen_session_is_rejected_before_send():
    hub = AiOpenCursorHub()
    screen = AsyncMock()
    await hub.connect(
        "expired", screen, {"owner_id": "3", "tenant_id": "7"}, authorize=lambda: False
    )
    result = await asyncio.to_thread(
        hub.dispatch_sync,
        "click",
        {"selector": "#delete"},
        owner_id="3",
        tenant_id="7",
        session_id="expired",
    )
    assert result["code"] == "SCREEN_SESSION_EXPIRED"
    screen.send_text.assert_not_called()
