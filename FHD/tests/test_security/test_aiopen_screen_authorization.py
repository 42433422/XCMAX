"""Screen dispatch and inventory are scoped to a server-bound owner and tenant."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.aiopen import service
from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
from app.domain.aiopen.principal import ScreenPrincipal
from app.fastapi_routes import ai_open, aiopen_access_dependency
from app.infrastructure.aiopen.cursor_hub import AiOpenCursorHub
from app.infrastructure.aiopen.principal_context import (
    current_screen_principal,
    screen_principal_scope,
)

ALICE = ScreenPrincipal("alice", "tenant-a")
BOB = ScreenPrincipal("bob", "tenant-a")
OTHER_TENANT = ScreenPrincipal("alice", "tenant-b")


class Screen:
    def __init__(self, hub, session_id):
        self.hub, self.session_id, self.sent = hub, session_id, []

    async def send_text(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        self.hub.handle_client_message(
            json.dumps({"id": message["id"], "result": {"success": True}}),
            session_id=self.session_id,
        )


async def seed(hub):
    # The foreign screen deliberately connects first.
    for session_id, owner in [("bob", BOB), ("other-tenant", OTHER_TENANT), ("alice", ALICE)]:
        await hub.connect(
            session_id,
            Screen(hub, session_id),
            {
                "principal_id": owner.principal_id,
                "tenant_id": owner.tenant_id,
            },
        )


def test_inventory_default_dispatch_and_history_are_owner_tenant_scoped():
    async def check():
        hub = AiOpenCursorHub()
        await seed(hub)
        with screen_principal_scope(ALICE):
            assert hub.session_ids() == ["alice"]
            assert [row["session_id"] for row in hub.sessions_info()] == ["alice"]
            result = await hub.dispatch("snapshot")
            assert result["session_id"] == "alice"
            assert len(hub.recent_commands()) == 1
        with screen_principal_scope(BOB):
            assert hub.session_ids() == ["bob"]
            assert hub.recent_commands() == []
        assert hub.session_ids() == []
        assert hub.sessions_info() == []
        assert hub.recent_commands() == []
        assert hub._sessions["bob"].sent == []
        assert hub._sessions["other-tenant"].sent == []

    asyncio.run(check())


@pytest.mark.parametrize("target", ["bob", "other-tenant", "missing"])
def test_known_foreign_and_missing_targets_are_indistinguishable(target):
    async def check():
        hub = AiOpenCursorHub()
        await seed(hub)
        with screen_principal_scope(ALICE):
            result = await hub.dispatch("snapshot", session_id=target)
        assert result == {
            "success": False,
            "code": "SCREEN_NOT_AUTHORIZED",
            "message": "目标屏幕不可访问",
        }
        assert all(not screen.sent for screen in hub._sessions.values())
        assert not hub._pending and not hub._command_log

    asyncio.run(check())


def test_unbound_principal_cannot_dispatch_even_with_known_target():
    async def check():
        hub = AiOpenCursorHub()
        await seed(hub)
        result = await hub.dispatch("snapshot", session_id="alice")
        assert result["code"] == "SCREEN_PRINCIPAL_REQUIRED"
        assert "alice" not in json.dumps(result)
        assert not hub._pending

    asyncio.run(check())


def test_context_restores_on_error_and_isolates_concurrent_tasks_and_threads():
    async def check():
        async def worker(owner):
            with screen_principal_scope(owner):
                await asyncio.sleep(0)
                assert current_screen_principal() == owner
                assert await asyncio.to_thread(current_screen_principal) == owner

        await asyncio.gather(worker(ALICE), worker(BOB), worker(OTHER_TENANT))
        with screen_principal_scope(ALICE):
            with pytest.raises(ValueError), screen_principal_scope(BOB):
                raise ValueError("fixture")
            assert current_screen_principal() == ALICE
        assert current_screen_principal() is None

    asyncio.run(check())


def test_registry_requires_complete_server_binding_and_honors_revocation():
    state = RuntimeState({"runtime_keys": {"legacy-fixture": {"label": "old"}}})
    keys = ApiKeyRegistry(state, lambda: "env-fixture", lambda count: "bound-fixture", lambda: 0)
    key = keys.generate("fixture", principal=ALICE)["key"]
    assert keys.resolve_principal(key) == ALICE
    for unbound in [None, "bad", "legacy-fixture", "env-fixture"]:
        assert keys.resolve_principal(unbound) is None
    assert keys.verify("legacy-fixture") and keys.verify("env-fixture")
    assert keys.revoke(key)
    assert keys.resolve_principal(key) is None
    for value in [None, "", False, {}, [], 3.5]:
        assert ScreenPrincipal.from_ids("alice", value) is None
    assert ScreenPrincipal.from_user(SimpleNamespace(id="alice")) is None


@pytest.fixture
def client(monkeypatch):
    hub = AiOpenCursorHub()
    asyncio.run(seed(hub))
    state = RuntimeState({"runtime_keys": {"legacy-fixture": {"label": "old"}}})
    keys = ApiKeyRegistry(state, lambda: "env-fixture", lambda count: "issued-fixture", lambda: 0)
    monkeypatch.setattr(service, "_keys", keys)
    monkeypatch.setattr(service, "aiopen_cursor_hub", hub)
    monkeypatch.setattr(ai_open, "aiopen_cursor_hub", hub)
    monkeypatch.setattr(aiopen_access_dependency, "resolve_session_user", lambda req: None)
    monkeypatch.setattr(
        ai_open, "create_chat_trace_run", Mock(return_value=SimpleNamespace(run_id="r"))
    )
    monkeypatch.setitem(service.AIOPEN_STATE, "remote_control_enabled", True)
    app = FastAPI()
    app.include_router(ai_open.router)
    app.dependency_overrides[ai_open.require_admin_user] = lambda: SimpleNamespace(
        id="alice",
        tenant_id="tenant-a",
        is_active=True,
    )
    with TestClient(app) as http:
        created = http.post(
            "/api/aiopen/keys",
            json={
                "label": "fixture",
                "principal_id": "bob",
                "user_id": "bob",
                "tenant_id": "tenant-b",
            },
        )
        assert created.status_code == 200
        key = created.json()["key"]
        assert keys.resolve_principal(key) == ALICE
        yield http, key, hub


@pytest.mark.parametrize("mcp", [False, True])
def test_real_key_binding_reaches_rest_and_mcp_dispatch(client, mcp):
    http, key, hub = client
    args = {"session_id": "bob", "user_id": "bob", "tenant_id": "tenant-a"}
    if mcp:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "ui_snapshot", "arguments": args},
        }
        response = http.post("/api/aiopen/mcp", json=body, headers={"X-AIOPEN-Key": key})
        assert response.json()["result"]["isError"] is True
    else:
        response = http.post(
            "/api/aiopen/invoke",
            json={"tool": "ui_snapshot", "args": args},
            headers={"X-AIOPEN-Key": key},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "SCREEN_NOT_AUTHORIZED"
    assert not hub._sessions["bob"].sent
    result = http.post(
        "/api/aiopen/invoke", json={"tool": "ui_sessions"}, headers={"X-AIOPEN-Key": key}
    ).json()
    assert [screen["session_id"] for screen in result["sessions"]] == ["alice"]


@pytest.mark.parametrize("key", ["legacy-fixture", "env-fixture"])
def test_unbound_keys_cannot_inherit_browser_authority(client, monkeypatch, key):
    http, _, _ = client
    monkeypatch.setattr(
        aiopen_access_dependency,
        "resolve_session_user",
        lambda req: SimpleNamespace(
            id="alice",
            tenant_id="tenant-a",
            is_active=True,
        ),
    )
    response = http.post(
        "/api/aiopen/invoke",
        json={"tool": "ui_snapshot"},
        headers={"X-AIOPEN-Key": key, "X-User-ID": "alice"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "SCREEN_PRINCIPAL_REQUIRED"
