"""Screen dispatch and inventory are scoped to a server-bound owner and tenant."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException, Request
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
from app.middleware.csrf import CSRFMiddleware
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

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


async def seed(hub, alice_owner=ALICE):
    # The foreign screen deliberately connects first.
    for session_id, owner in [("bob", BOB), ("other-tenant", OTHER_TENANT), ("alice", alice_owner)]:
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
def client(monkeypatch, trusted_actor):
    actor = trusted_actor(user_id=17, role="admin", tier="admin")
    owner = ScreenPrincipal(str(actor.user_id), str(actor.tenant_id))
    hub = AiOpenCursorHub()
    asyncio.run(seed(hub, owner))
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
    with TestClient(app) as http:
        created = http.post(
            "/api/aiopen/keys",
            json={
                "label": "fixture",
                "principal_id": "bob",
                "user_id": "bob",
                "tenant_id": "tenant-b",
            },
            headers=actor.headers,
        )
        assert created.status_code == 200
        key = created.json()["key"]
        assert keys.resolve_principal(key) == owner
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


def test_client_key_is_session_owned_revocable_and_scope_limited(monkeypatch, tmp_path):
    hub = AiOpenCursorHub()
    asyncio.run(seed(hub))
    storage = tmp_path / "keys.json"
    registry = ApiKeyRegistry(
        RuntimeState({}), lambda: "", secrets.token_urlsafe, time.time, lambda: storage
    )
    monkeypatch.setattr(service, "_keys", registry)
    monkeypatch.setattr(service, "aiopen_cursor_hub", hub)
    monkeypatch.setattr(aiopen_access_dependency, "resolve_session_user", lambda req: None)
    monkeypatch.setattr(
        ai_open, "create_chat_trace_run", Mock(return_value=SimpleNamespace(run_id="client-test"))
    )
    monkeypatch.setitem(service.AIOPEN_STATE, "remote_control_enabled", True)
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)
    app.include_router(ai_open.router)
    accounts = {p: owner for p, owner in (("a", ALICE), ("b", BOB), ("other", OTHER_TENANT))}

    def logged_in(request: Request):
        owner = accounts.get(request.cookies.get("session"))
        if owner is None:
            raise HTTPException(status_code=401)
        return SimpleNamespace(
            id=owner.principal_id, tenant_id=owner.tenant_id, tier="enterprise", is_active=True
        )

    app.dependency_overrides[ai_open.get_logged_in_user] = logged_in
    key_path = "/api/aiopen/client/key"
    copy_path = f"{key_path}?keep_existing=true"
    with TestClient(app) as http:
        assert http.get("/api/aiopen/client").status_code == 401
        csrf = {"X-CSRF-Token": http.cookies["csrf_token"]}
        assert http.post(key_path, headers=csrf).status_code == 401
        http.cookies.set("session", "a")
        assert http.post(key_path).status_code == 403
        assert http.delete(key_path).status_code == 403
        created = http.post(
            key_path,
            headers=csrf,
            json={"principal_id": "bob", "tenant_id": "tenant-b", "scopes": ["*"]},
        )
        assert created.status_code == 200 and created.headers["cache-control"] == "no-store"
        key = created.json()["key"]
        assert key not in storage.read_text()
        restarted = ApiKeyRegistry(
            RuntimeState({}), lambda: "", secrets.token_urlsafe, time.time, lambda: storage
        )
        assert restarted.resolve_principal(key) == ALICE
        assert not restarted.verify(key)
        inspected = http.get("/api/aiopen/client").json()
        assert inspected["client_mode"] and inspected["has_active_key"]
        assert key not in json.dumps(inspected)

        headers = {"X-AIOPEN-Key": key}
        for index, method, params in (
            (1, "initialize", {"protocolVersion": "2025-06-18"}),
            (2, "tools/list", {}),
            (3, "tools/call", {"name": "ui_sessions"}),
        ):
            payload = {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
            result = http.post("/api/aiopen/mcp", headers=headers, json=payload).json()["result"]
            if index == 1:
                assert result["serverInfo"]["name"] == "AIOPEN"
            elif index == 2:
                assert len(result["tools"]) == len(service.TOOL_DEFINITIONS)
                assert "api_call" not in {tool["name"] for tool in result["tools"]}
            else:
                show = result["content"][0]["text"]
                assert "alice" in show and "bob" not in show and "other-tenant" not in show
        forbidden = {"tool": "chat", "args": {"message": "blocked"}}
        assert http.post("/api/aiopen/invoke", headers=headers, json=forbidden).status_code == 403
        for path in ("/api/aiopen/loop/verify",):
            rejected = http.post(path, headers=headers, json={"message": "blocked"})
            assert rejected.status_code == 403
            assert rejected.json()["code"] == "AIOPEN_SCOPE_DENIED"
        assert (
            http.post(
                "/api/aiopen/openclaw/chat", headers=headers, json={"message": "blocked"}
            ).status_code
            == 404
        )
        for account in ("b", "other"):
            http.cookies.set("session", account)
            assert not http.get("/api/aiopen/client").json()["has_active_key"]
            assert http.delete(key_path, headers=csrf).json()["revoked"] is False
        assert registry.authorize(key, "ui_sessions")["ok"]
        http.cookies.set("session", "a")
        with monkeypatch.context() as broken:
            broken.setattr(registry, "_persist", lambda: False)
            assert http.post(key_path, headers=csrf).status_code == 503
            assert http.post(copy_path, headers=csrf).status_code == 503
            assert http.delete(key_path, headers=csrf).status_code == 503
            assert registry.authorize(key, "ui_sessions")["ok"]

        assert http.post(copy_path).status_code == 403
        alice_keys = [key]
        for _ in range(7):
            copy = http.post(copy_path, headers=csrf)
            assert copy.status_code == 200 and copy.headers["cache-control"] == "no-store"
            alice_keys.append(copy.json()["key"])
        assert len(set(alice_keys)) == 8
        assert http.post(copy_path, headers=csrf).status_code == 409
        assert all(registry.authorize(secret, "ui_sessions")["ok"] for secret in alice_keys)

        http.cookies.set("session", "other")
        other_key = http.post(copy_path, headers=csrf).json()["key"]
        assert registry.resolve_principal(other_key) == OTHER_TENANT

        http.cookies.set("session", "a")
        rotated = http.post(key_path, headers=csrf).json()["key"]
        assert all(not registry.authorize(secret)["ok"] for secret in alice_keys)
        copied = http.post(copy_path, headers=csrf).json()["key"]
        assert http.delete(key_path, headers=csrf).json()["revoked"] is True
        assert not registry.authorize(rotated)["ok"] and not registry.authorize(copied)["ok"]
        assert registry.authorize(other_key, "ui_sessions")["ok"]
        assert http.post("/api/aiopen/mcp", headers=headers, json={}).status_code == 401


def test_client_key_copy_prunes_only_expired_keys_for_owner(tmp_path):
    now = 100.0
    storage = tmp_path / "keys.json"
    registry = ApiKeyRegistry(
        RuntimeState({}), lambda: "", secrets.token_urlsafe, lambda: now, lambda: storage
    )
    client_options = {"scopes": ["ui_sessions"], "client_key": True, "keep_existing": True}
    expired = registry.generate(principal=ALICE, expires_at=100.25, **client_options)["key"]
    active = registry.generate(principal=ALICE, expires_at=100.75, **client_options)["key"]
    other = registry.generate(principal=OTHER_TENANT, expires_at=100.25, **client_options)["key"]
    service_key = registry.generate(principal=ALICE, expires_at=100.25)["key"]

    now = 100.5
    copied = registry.generate(principal=ALICE, expires_at=200, **client_options)["key"]
    restarted = ApiKeyRegistry(
        RuntimeState({}), lambda: "", secrets.token_urlsafe, lambda: now, lambda: storage
    )
    assert restarted.resolve_principal(expired) is None
    for key, owner in (
        (active, ALICE),
        (copied, ALICE),
        (other, OTHER_TENANT),
        (service_key, ALICE),
    ):
        assert restarted.resolve_principal(key) == owner
