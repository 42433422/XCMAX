"""AIOPEN 开放平台（原 Qclaw龙虾生态 toA 升级）端到端测试。

覆盖：manifest 公开访问、invoke 鉴权 401 / 白名单 403、
MCP JSON-RPC（initialize → tools/list → tools/call）、
旧 ``/api/ai/qclaw/*`` URL 兼容与状态共享。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.aiopen import service as aiopen_service
from app.application.aiopen.service import AIOPEN_STATE
from app.fastapi_routes.ai_open import router as ai_open_router
from app.fastapi_routes.ai_qclaw import _QCLOW_RUNTIME_STATE
from app.fastapi_routes.ai_qclaw import router as ai_qclaw_router
from app.infrastructure.auth.dependencies import require_admin_user
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture()
def admin_actor(trusted_actor):
    return trusted_actor(user_id=73, role="admin", tier="admin", tenant_id=None)


@pytest.fixture()
def client(monkeypatch, admin_actor):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    app = FastAPI()
    app.include_router(ai_open_router)
    app.include_router(ai_qclaw_router)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=73,
        tier="admin",
        role="admin",
    )
    return TestClient(app, headers={**admin_actor.headers, "X-AIOPEN-Key": "fixture-aiopen-key"})


@pytest.fixture(autouse=True)
def _reset_runtime_keys():
    AIOPEN_STATE["runtime_keys"] = {}
    yield
    AIOPEN_STATE["runtime_keys"] = {}


def test_state_alias_shared():
    """旧 _QCLOW_RUNTIME_STATE 必须与 AIOPEN_STATE 同一对象（URL 契约共享状态）。"""
    assert _QCLOW_RUNTIME_STATE is AIOPEN_STATE


def test_manifest_public(client):
    resp = client.get("/api/aiopen/manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["name"] == "AIOPEN"
    from app.infrastructure.mods.manifest import host_xcagi_version

    assert data["version"] == host_xcagi_version()
    assert data["protocol"]["guide"] == "/api/aiopen/guide"
    tool_names = {t["name"] for t in data["tools"]}
    assert {"api_catalog", "api_call", "chat", "ui_snapshot", "ui_click", "ui_type"} <= tool_names


def test_guide_json_and_markdown(client):
    j = client.get("/api/aiopen/guide").json()
    assert j["success"] is True
    assert "markdown" in j and "mcp_config_template" in j
    assert "prompt_for_user" in j
    assert "xcagi-aiopen" in j["mcp_config_template"]["mcpServers"]
    assert "/api/aiopen/mcp" in j["endpoints"]["mcp"]
    assert "cursor_deeplink" in j
    assert "install_url" in j

    md = client.get("/api/aiopen/guide?format=markdown")
    assert md.status_code == 200
    assert "text/markdown" in (md.headers.get("content-type") or "")
    assert "XCAGI AIOPEN 接入说明" in md.text
    assert "ui_snapshot" in md.text


def test_invoke_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "secret-key-1")
    resp = client.post("/api/aiopen/invoke", json={"tool": "api_catalog", "args": {}})
    assert resp.status_code == 401
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "api_catalog", "args": {}},
        headers={"X-AIOPEN-Key": "wrong"},
    )
    assert resp.status_code == 401
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "api_catalog", "args": {}},
        headers={"X-AIOPEN-Key": "secret-key-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_invoke_denied_when_no_keys(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    resp = client.post("/api/aiopen/invoke", json={"tool": "api_catalog", "args": {}})
    assert resp.status_code == 401
    assert resp.json()["code"] == "AIOPEN_KEY_INVALID"


def test_aiopen_invoke_attaches_agent_run_for_tool_call(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    repo = InMemoryAgentRunRepository()

    from app.fastapi_routes import ai_open

    with (
        patch("app.fastapi_routes.ai_open.invoke_tool", wraps=ai_open.invoke_tool) as invoke,
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        resp = client.post(
            "/api/aiopen/invoke",
            json={"tool": "api_catalog", "args": {}, "user_id": "aiopen-rest-user"},
        )

    invoke.assert_awaited_once()
    assert invoke.call_args.args[:2] == ("api_catalog", {})
    assert resp.status_code == 200
    body = resp.json()
    run_id = body["run_id"]
    assert body["agent_run_id"] == run_id
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "aiopen-api-key"  # body user_id must not spoof
    assert run.intent == "aiopen_tool_call"
    assert run.metadata["channel"] == "aiopen_invoke"
    assert run.metadata["runtime_context"]["route"] == "/api/aiopen/invoke"
    _assert_redacted_aiopen_receipt(run)


def _assert_redacted_aiopen_receipt(run):
    # A verified external call remains auditable without inventing an internal
    # orchestrator execution or charging its cost a second time.
    assert run.status == "completed"
    assert not run.tool_calls
    payload = run.final_output["chat_payload"]
    assert payload["success"] is True
    records = payload["data"]["legacy_tool_records"]
    assert len(records) == 1
    assert records[0]["tool_id"] == "aiopen"
    assert records[0]["action"] == "api_catalog"
    assert records[0]["params"] == str({"payload_redacted": True, "argument_count": 0})
    assert records[0]["output"] == str({"payload_redacted": True, "success": True})
    assert "fixture-aiopen-key" not in str(run.to_dict())
    assert "run.completed" in [event.event_type for event in run.events]
    assert "tool.request_rejected" not in [event.event_type for event in run.events]


def test_invoke_api_call_blocked_outside_whitelist(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "api_call", "args": {"path": "/api/not/whitelisted"}},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "ROUTE_NOT_WHITELISTED"


def test_invoke_unknown_tool(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    resp = client.post("/api/aiopen/invoke", json={"tool": "nope", "args": {}})
    assert resp.status_code == 404


def test_runtime_key_lifecycle(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    created = client.post("/api/aiopen/keys", json={"label": "测试"}).json()
    assert created["success"] is True
    assert created["run_id"] == created["agent_run_id"]
    key = created["key"]
    assert key.startswith("aiopen_")

    # 配置 Key 后必须携带
    resp = client.post("/api/aiopen/invoke", json={"tool": "api_catalog"})
    assert resp.status_code == 401
    resp = client.post(
        "/api/aiopen/invoke", json={"tool": "api_catalog"}, headers={"X-AIOPEN-Key": key}
    )
    assert resp.status_code == 200

    # 吊销后失效（无任何 Key → 回到直通）
    resp = client.request("DELETE", "/api/aiopen/keys", json={"key": key})
    assert resp.json()["revoked"] is True
    assert resp.json()["run_id"] == resp.json()["agent_run_id"]
    assert aiopen_service.list_api_keys() == []
    # Revoking the last key must not reopen the API to unauthenticated clients.
    assert client.post("/api/aiopen/invoke", json={"tool": "api_catalog"}).status_code == 401


def test_aiopen_key_lifecycle_traces_without_key_leak(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    repo = InMemoryAgentRunRepository()

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        created = client.post(
            "/api/aiopen/keys",
            json={"label": "trace-key", "user_id": "key-admin"},
        ).json()
        key = created["key"]
        revoked = client.request("DELETE", "/api/aiopen/keys", json={"key": key}).json()

    create_run = repo.get(created["run_id"])
    assert create_run is not None
    assert create_run.user_id == "73"  # verified admin id, not body user_id
    assert create_run.intent == "aiopen_control_update"
    assert create_run.metadata["channel"] == "aiopen_control"
    assert create_run.metadata["runtime_context"]["route"] == "/api/aiopen/keys"
    assert create_run.metadata["runtime_context"]["action"] == "keys_create"
    assert key not in str(create_run.to_dict())

    revoke_run = repo.get(revoked["run_id"])
    assert revoke_run is not None
    assert revoke_run.intent == "aiopen_control_update"
    assert revoke_run.metadata["runtime_context"]["action"] == "keys_revoke"
    assert "key_preview" in revoke_run.metadata["runtime_context"]["request"]
    assert "key" not in revoke_run.metadata["runtime_context"]["request"]
    assert key not in str(revoke_run.to_dict())


def test_aiopen_control_routes_attach_agent_runs(client):
    repo = InMemoryAgentRunRepository()

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        whitelist = client.post(
            "/api/aiopen/whitelist",
            json={"path": "/api/aiopen/control-smoke", "enabled": True},
        ).json()
        config = client.post(
            "/api/aiopen/config", json={"base_url": "http://openclaw.test:28789"}
        ).json()
        control = client.post("/api/aiopen/control", json={"enabled": True}).json()

    for payload, route, action in (
        (whitelist, "/api/aiopen/whitelist", "whitelist_update"),
        (config, "/api/aiopen/config", "openclaw_config_update"),
        (control, "/api/aiopen/control", "remote_control_update"),
    ):
        run_id = payload["run_id"]
        assert payload["agent_run_id"] == run_id
        run = repo.get(run_id)
        assert run is not None
        assert run.intent == "aiopen_control_update"
        assert run.metadata["channel"] == "aiopen_control"
        assert run.metadata["runtime_context"]["route"] == route
        assert run.metadata["runtime_context"]["action"] == action

    AIOPEN_STATE["whitelist"].pop("/api/aiopen/control-smoke", None)
    AIOPEN_STATE["openclaw_base"] = "http://localhost:28789"
    AIOPEN_STATE["remote_control_enabled"] = True


def test_mcp_initialize_list_call(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")

    init = client.post(
        "/api/aiopen/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    ).json()
    assert init["result"]["serverInfo"]["name"] == "AIOPEN"
    assert init["result"]["capabilities"]["tools"] is not None

    # notification → 202
    note = client.post(
        "/api/aiopen/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert note.status_code == 202

    tools = client.post(
        "/api/aiopen/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ).json()
    names = {t["name"] for t in tools["result"]["tools"]}
    assert "api_catalog" in names and "ui_click" in names

    call = client.post(
        "/api/aiopen/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "api_catalog", "arguments": {}},
        },
    ).json()
    assert call["result"]["isError"] is False
    assert "/api/ai/unified_chat" in call["result"]["content"][0]["text"]
    assert "白名单" in call["result"]["content"][0]["text"]

    ping = client.post("/api/aiopen/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "ping"})
    assert ping.headers.get("MCP-Protocol-Version")
    ping_body = ping.json()
    assert ping_body["result"] == {}

    unknown = client.post(
        "/api/aiopen/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "bogus/method"}
    ).json()
    assert unknown["error"]["code"] == -32601


def test_aiopen_mcp_tools_call_attaches_agent_run_meta(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    repo = InMemoryAgentRunRepository()

    from app.fastapi_routes import ai_open

    with (
        patch("app.fastapi_routes.ai_open.invoke_tool", wraps=ai_open.invoke_tool) as invoke,
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        resp = client.post(
            "/api/aiopen/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 30,
                "method": "tools/call",
                "params": {"name": "api_catalog", "arguments": {}},
            },
        )

    invoke.assert_awaited_once()
    assert invoke.call_args.args[:2] == ("api_catalog", {})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["isError"] is False
    run_id = result["_meta"]["run_id"]
    assert result["_meta"]["agent_run_id"] == run_id
    run = repo.get(run_id)
    assert run is not None
    assert run.intent == "aiopen_tool_call"
    assert run.metadata["channel"] == "aiopen_mcp"
    assert run.metadata["runtime_context"]["route"] == "/api/aiopen/mcp"
    _assert_redacted_aiopen_receipt(run)


def test_mcp_get_probe(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    resp = client.get("/api/aiopen/mcp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["transport"] == "streamable-http"
    assert data["tool_count"] >= 9
    assert resp.headers.get("MCP-Protocol-Version")


def test_install_bundle(client):
    resp = client.get("/api/aiopen/install")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["server_name"] == "xcagi-aiopen"
    assert "url" in data["methods"]
    assert "cursor_deeplink" in data["methods"]["url"]
    assert data["methods"]["url"]["cursor_deeplink"].startswith("cursor://")
    clients = data.get("clients") or []
    assert len(clients) >= 6
    ids = {c["id"] for c in clients}
    assert {"cursor", "claude", "vscode", "windsurf", "generic"} <= ids
    cursor = next(c for c in clients if c["id"] == "cursor")
    assert "mcp_json" in cursor and "xcagi-aiopen" in cursor["mcp_json"]


def test_mcp_initialize_session_header(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    resp = client.post(
        "/api/aiopen/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("Mcp-Session-Id")
    body = resp.json()
    assert body["result"]["protocolVersion"] == "2024-11-05"
    assert "ui_sessions" in body["result"]["instructions"]


def test_ui_tool_without_session(client, monkeypatch):
    """Env/unbound keys authenticate the service but cannot operate screens."""
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    AIOPEN_STATE["remote_control_enabled"] = True
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "ui_snapshot", "args": {}},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "SCREEN_PRINCIPAL_REQUIRED"


def test_ui_tool_blocked_when_remote_control_off(client, monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    AIOPEN_STATE["remote_control_enabled"] = False
    try:
        resp = client.post("/api/aiopen/invoke", json={"tool": "ui_click", "args": {}})
        assert resp.json()["code"] == "REMOTE_CONTROL_DISABLED"
    finally:
        AIOPEN_STATE["remote_control_enabled"] = True


def test_legacy_qclaw_urls_share_state(client):
    panel = client.get("/api/ai/qclaw/panel").json()
    assert panel["success"] is True

    # 经旧 URL 改白名单 → 新面板可见
    resp = client.post(
        "/api/ai/qclaw/whitelist", json={"path": "/api/legacy/test", "enabled": True}
    )
    assert resp.json()["success"] is True
    new_panel = client.get("/api/aiopen/panel").json()
    assert {"path": "/api/legacy/test", "enabled": True} in new_panel["routes"]

    # 经新 URL 改 openclaw_base → 旧面板可见
    client.post("/api/aiopen/config", json={"base_url": "http://example.test:28789"})
    legacy_panel = client.get("/api/ai/qclaw/panel").json()
    assert legacy_panel["openclaw_base"] == "http://example.test:28789"

    # 还原，避免污染其他测试
    AIOPEN_STATE["whitelist"].pop("/api/legacy/test", None)
    AIOPEN_STATE["openclaw_base"] = "http://localhost:28789"


def test_qclaw_control_and_test_route_attach_agent_runs(monkeypatch):
    monkeypatch.setenv("AIOPEN_API_KEY", "fixture-aiopen-key")
    app = FastAPI()

    @app.get("/api/qclaw/smoke")
    def qclaw_smoke():
        return {"success": True, "source": "smoke"}

    app.include_router(ai_open_router)
    app.include_router(ai_qclaw_router)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=73,
        tier="admin",
        role="admin",
    )
    repo = InMemoryAgentRunRepository()

    with (
        TestClient(app, headers={"X-AIOPEN-Key": "fixture-aiopen-key"}) as local_client,
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        wechat = local_client.post("/api/ai/qclaw/wechat-gateway", json={"enabled": True}).json()
        config = local_client.post(
            "/api/ai/qclaw/openclaw/config",
            json={"base_url": "http://qclaw-openclaw.test:28789"},
        ).json()
        whitelist = local_client.post(
            "/api/ai/qclaw/whitelist",
            json={"path": "/api/qclaw/smoke", "enabled": True},
        ).json()
        smoke = local_client.post(
            "/api/ai/qclaw/test-route",
            json={"path": "/api/qclaw/smoke", "method": "GET"},
        ).json()

    for payload, route, action in (
        (wechat, "/api/ai/qclaw/wechat-gateway", "wechat_gateway_update"),
        (config, "/api/ai/qclaw/openclaw/config", "openclaw_config_update"),
        (whitelist, "/api/ai/qclaw/whitelist", "whitelist_update"),
    ):
        run_id = payload["run_id"]
        assert payload["agent_run_id"] == run_id
        run = repo.get(run_id)
        assert run is not None
        assert run.intent == "qclaw_control_update"
        assert run.metadata["channel"] == "qclaw_control"
        assert run.metadata["source"] == "qclaw"
        assert run.metadata["runtime_context"]["route"] == route
        assert run.metadata["runtime_context"]["action"] == action

    smoke_run_id = smoke["run_id"]
    assert smoke["agent_run_id"] == smoke_run_id
    assert smoke["status_code"] == 200
    smoke_run = repo.get(smoke_run_id)
    assert smoke_run is not None
    assert smoke_run.intent == "qclaw_route_smoke"
    assert smoke_run.metadata["channel"] == "qclaw_route_smoke"
    assert smoke_run.metadata["runtime_context"]["route"] == "/api/ai/qclaw/test-route"
    assert smoke_run.metadata["runtime_context"]["request"]["path"] == "/api/qclaw/smoke"

    AIOPEN_STATE["whitelist"].pop("/api/qclaw/smoke", None)
    AIOPEN_STATE["openclaw_base"] = "http://localhost:28789"
    AIOPEN_STATE["wechat_open"] = False


@pytest.mark.parametrize("path", ["/api/aiopen/openclaw/chat", "/api/ai/qclaw/openclaw/chat"])
def test_legacy_openclaw_chat_does_not_dispatch_or_create_receipt(client, path):
    with (
        patch.object(aiopen_service, "openclaw_chat_proxy") as proxy,
        patch("app.application.agent_orchestrator.chat_trace.get_agent_run_repository") as repo,
    ):
        response = client.post(path, json={"message": "send", "user_id": "forged"})
    assert response.status_code == 410
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "openclaw_legacy_route_retired"
    assert body["execution_state"] == "not_started"
    assert body["retryable"] is False
    assert "run_id" not in body and "agent_run_id" not in body
    proxy.assert_not_called()
    repo.assert_not_called()


def test_screen_ws_command_roundtrip(client, monkeypatch):
    """A trusted authenticated screen is visible only to a matching bound key."""
    from app.application.aiopen.service import generate_api_key
    from app.domain.aiopen.principal import ScreenPrincipal
    from app.fastapi_routes import ai_open as ai_open_routes

    AIOPEN_STATE["remote_control_enabled"] = True
    owner = ScreenPrincipal.from_ids(27, 42)
    assert owner is not None
    issued = generate_api_key("pytest-screen", principal=owner)["key"]
    monkeypatch.setattr(
        ai_open_routes,
        "resolve_session_user",
        lambda ws: SimpleNamespace(id=27, tenant_id=42, is_active=True),
    )
    with client.websocket_connect(
        "/api/aiopen/ws?session_id=attacker_supplied&label=pytest",
        headers={"Origin": "http://testserver"},
    ) as ws:
        hello = ws.receive_json()
        session_id = hello["session_id"]
        assert session_id.startswith("screen_")
        assert session_id != "attacker_supplied"

        sessions = client.post(
            "/api/aiopen/invoke",
            json={"tool": "ui_sessions", "args": {}},
            headers={"X-AIOPEN-Key": issued},
        ).json()
        assert any(s["session_id"] == session_id for s in sessions["sessions"])


def test_aiopen_source_alias():
    from app.utils.ai_helpers import is_qclaw_source

    assert is_qclaw_source("aiopen")
    assert is_qclaw_source("qclaw")
    assert is_qclaw_source("lobster")
    assert not is_qclaw_source("pro")


def test_aiopen_and_qclaw_management_denied_without_admin_session(monkeypatch):
    """Anonymous clients cannot create keys or change global policy via either URL family."""
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(ai_open_router)
    app.include_router(ai_qclaw_router)
    routes = [
        ("GET", "/api/aiopen/keys"),
        ("POST", "/api/aiopen/keys"),
        ("DELETE", "/api/aiopen/keys"),
        ("GET", "/api/aiopen/panel"),
        ("POST", "/api/aiopen/whitelist"),
        ("POST", "/api/aiopen/whitelist/seed"),
        ("POST", "/api/aiopen/config"),
        ("POST", "/api/aiopen/control"),
        ("GET", "/api/ai/qclaw/panel"),
        ("POST", "/api/ai/qclaw/wechat-gateway"),
        ("POST", "/api/ai/qclaw/openclaw/config"),
        ("POST", "/api/ai/qclaw/whitelist"),
        ("POST", "/api/ai/qclaw/test-route"),
    ]
    with TestClient(app) as unauthenticated:
        for method, path in routes:
            response = unauthenticated.request(method, path, json={} if method != "GET" else None)
            assert response.status_code == 401, (method, path, response.text)


def test_non_admin_cannot_manage_aiopen(monkeypatch):
    """A verified ordinary user must not become an AIOPEN administrator."""
    from app.infrastructure.auth import dependencies

    app = FastAPI()
    app.include_router(ai_open_router)
    monkeypatch.setattr(
        dependencies,
        "get_logged_in_user",
        lambda request: SimpleNamespace(tier="normal", role="user", is_active=True),
    )
    with TestClient(app) as ordinary:
        assert ordinary.post("/api/aiopen/keys", json={"label": "forbidden"}).status_code == 403
        assert ordinary.post("/api/aiopen/control", json={"enabled": True}).status_code == 403


def test_direct_aiopen_and_legacy_qclaw_tools_require_key(monkeypatch):
    """Unauthenticated probes and chat proxies cannot bypass /invoke protection."""
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(ai_open_router)
    app.include_router(ai_qclaw_router)
    with TestClient(app) as unauthenticated:
        for path in (
            "/api/aiopen/loop/verify",
            "/api/aiopen/openclaw/chat",
            "/api/ai/qclaw/openclaw/chat",
        ):
            assert unauthenticated.post(path, json={"message": "test"}).status_code == 401


def test_issued_delegated_key_binds_request_scope_and_revocation(trusted_actor, tmp_path, monkeypatch):
    from fastapi import Depends

    from app.application.aiopen.runtime import ApiKeyRegistry, RuntimeState
    from app.fastapi_routes.aiopen_access_dependency import bind_aiopen_principal
    from app.infrastructure.aiopen.principal_context import current_execution_context

    admin = trusted_actor(user_id=73, role="admin", tier="admin", tenant_id=7)
    other = trusted_actor(user_id=74, tenant_id=8)
    registry = ApiKeyRegistry(
        RuntimeState({}), lambda: "", lambda _: "fixture", lambda: 100.0,
        lambda: tmp_path / "delegated-keys.json",
    )
    monkeypatch.setattr(aiopen_service, "_keys", registry)
    app = FastAPI()
    app.include_router(ai_open_router)
    app.dependency_overrides[require_admin_user] = lambda: SimpleNamespace(
        id=73, tenant_id=7, role="admin", tier="admin", is_active=True
    )

    @app.get("/scope", dependencies=[Depends(bind_aiopen_principal)])
    def scope():
        context = current_execution_context()
        return {
            "user_id": context.get("user_id"),
            "request_id": context.get("idempotency_key"),
            "delegated": "_credential_authorization" in context,
        }

    with TestClient(app) as client:
        created = client.post(
            "/api/aiopen/keys",
            headers=admin.headers,
            json={"label": "delegated", "scopes": ["capability.customers.list"], "user_id": "74"},
        )
        assert created.status_code == 200, created.text
        key = created.json()["key"]
        original = registry.resolve_execution_context(key)
        assert original is not None
        assert original["user_id"] == "73"
        assert registry.permits_execution(original, "customers", "list")
        assert not registry.permits_execution(original, "customers", "create")
        headers = {**other.headers, "X-AIOPEN-Key": key, "Idempotency-Key": "stable-request"}
        assert client.get("/scope", headers=headers).json() == {
            "user_id": "73", "request_id": "stable-request", "delegated": True
        }
        assert current_execution_context() == {}
        assert client.get("/scope", headers=other.headers).json()["user_id"] == "74"
        revoked = client.request("DELETE", "/api/aiopen/keys", headers=admin.headers, json={"key": key})
        assert revoked.status_code == 200 and revoked.json()["revoked"] is True
        assert not registry.execution_context_current(original)
        assert client.get("/scope", headers=headers).json() == {
            "user_id": None, "request_id": None, "delegated": False
        }


def test_key_revocation_failure_is_not_reported_as_revoked(client, monkeypatch):
    def fail(_key):
        raise OSError("private persistence details")

    monkeypatch.setattr("app.fastapi_routes.ai_open.revoke_api_key", fail)
    response = client.request("DELETE", "/api/aiopen/keys", json={"key": "original-key"})
    assert response.status_code == 503
    assert response.json()["success"] is False and response.json()["revoked"] is False
    assert response.json()["error_code"] == "key_revocation_unavailable"
    assert "private" not in response.text and "original-key" not in response.text


def test_probe_alias_uses_shared_key_scope_and_rate_limit(client, monkeypatch):
    from app.application.aiopen import service

    calls = []

    async def probe(*args):
        calls.append(args)
        return {"success": True, "checks": []}

    monkeypatch.setattr("app.fastapi_routes.ai_open.invoke_tool", probe)
    wrong_scope = service.generate_api_key("other", scopes=["ui_snapshot"])["key"]
    denied = client.post("/api/aiopen/loop/verify", headers={"X-AIOPEN-Key": wrong_scope}, json={})
    assert denied.status_code == 403 and denied.json()["code"] == "AIOPEN_SCOPE_DENIED"
    assert calls == []

    limited = service.generate_api_key("probe", scopes=["capability_loop"], rate_limit_per_min=1)[
        "key"
    ]
    first = client.post("/api/aiopen/loop/verify", headers={"X-AIOPEN-Key": limited}, json={})
    assert first.status_code == 200
    replay = client.post(
        "/api/aiopen/invoke",
        headers={"X-AIOPEN-Key": limited},
        json={"tool": "capability_loop", "args": {}},
    )
    assert replay.status_code == 429 and replay.json()["code"] == "AIOPEN_RATE_LIMITED"
    assert len(calls) == 1


def test_aiopen_tool_trace_uses_bound_execution_identity(monkeypatch):
    from app.fastapi_routes import ai_open
    from app.infrastructure.aiopen.principal_context import execution_context_scope

    captured = {}

    def trace(**kwargs):
        captured.update(kwargs)
        return "trace-run"

    monkeypatch.setattr(ai_open, "trace_tool_call", trace)
    with execution_context_scope({"user_id": "73"}):
        result = ai_open._trace_aiopen_tool_call(
            route="/api/aiopen/invoke",
            channel="aiopen_invoke",
            tool="capability_loop",
            args={"user_id": "74"},
            result={"success": True},
            user_id="aiopen-api-key",
        )
    assert result == "trace-run"
    assert captured["user_id"] == "73"


@pytest.mark.parametrize(
    ("payload", "expected_ok"),
    [
        ({"success": True}, True),
        ({"success": False}, False),
        ({}, False),
        ({"success": "true"}, False),
        ({"success": True, "reconciliation_required": True}, False),
    ],
)
def test_aiopen_usage_preserves_business_outcome(client, monkeypatch, payload, expected_ok):
    from app.fastapi_routes import ai_open

    usage = []

    async def invoke(*_args):
        return payload

    def record(_key, _tool, *, channel, ok, duration_ms):
        usage.append((channel, ok))

    monkeypatch.setattr(ai_open, "invoke_tool", invoke)
    monkeypatch.setattr(ai_open, "record_api_key_use", record)
    monkeypatch.setattr(ai_open, "_trace_aiopen_tool_call", lambda **_kwargs: "")
    monkeypatch.setattr(ai_open, "format_tool_result_text", lambda *_args: "")
    rest = client.post("/api/aiopen/invoke", json={"tool": "api_catalog", "args": {}})
    assert rest.status_code == 200
    mcp = client.post(
        "/api/aiopen/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "api_catalog", "arguments": {}},
        },
    )
    assert mcp.status_code == 200
    assert mcp.json()["result"]["isError"] is (not expected_ok)
    assert usage == [("rest", expected_ok), ("mcp", expected_ok)]
