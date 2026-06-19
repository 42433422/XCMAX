"""AIOPEN 开放平台（原 Qclaw龙虾生态 toA 升级）端到端测试。

覆盖：manifest 公开访问、invoke 鉴权 401 / 白名单 403、
MCP JSON-RPC（initialize → tools/list → tools/call）、
旧 ``/api/ai/qclaw/*`` URL 兼容与状态共享。
"""

from __future__ import annotations

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


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(ai_open_router)
    app.include_router(ai_qclaw_router)
    return TestClient(app)


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
    assert data["version"] == "10.0.0"
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


def test_invoke_open_when_no_keys(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    resp = client.post("/api/aiopen/invoke", json={"tool": "api_catalog", "args": {}})
    assert resp.status_code == 200
    routes = {r["path"] for r in resp.json()["routes"]}
    assert "/api/ai/unified_chat" in routes


def test_aiopen_invoke_attaches_agent_run_for_tool_call(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    repo = InMemoryAgentRunRepository()

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
    ):
        resp = client.post(
            "/api/aiopen/invoke",
            json={"tool": "api_catalog", "args": {}, "user_id": "aiopen-rest-user"},
        )

    assert resp.status_code == 200
    body = resp.json()
    run_id = body["run_id"]
    assert body["agent_run_id"] == run_id
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "aiopen-rest-user"
    assert run.intent == "aiopen_tool_call"
    assert run.metadata["channel"] == "aiopen_invoke"
    assert run.metadata["runtime_context"]["route"] == "/api/aiopen/invoke"
    assert run.metadata["tool_call_count"] == 1
    assert run.tool_calls[0].tool_id == "aiopen"
    assert run.tool_calls[0].action == "api_catalog"
    assert run.tool_calls[0].cost_units == 1


def test_invoke_api_call_blocked_outside_whitelist(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "api_call", "args": {"path": "/api/not/whitelisted"}},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "ROUTE_NOT_WHITELISTED"


def test_invoke_unknown_tool(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
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
    assert create_run.user_id == "key-admin"
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
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)

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
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    repo = InMemoryAgentRunRepository()

    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
        return_value=repo,
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
    assert run.tool_calls[0].tool_id == "aiopen"
    assert run.tool_calls[0].action == "api_catalog"


def test_mcp_get_probe(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
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
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
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
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
    AIOPEN_STATE["remote_control_enabled"] = True
    resp = client.post(
        "/api/aiopen/invoke",
        json={"tool": "ui_snapshot", "args": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "虚拟光标会话" in body["message"]


def test_ui_tool_blocked_when_remote_control_off(client, monkeypatch):
    monkeypatch.delenv("AIOPEN_API_KEY", raising=False)
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


def test_qclaw_control_and_test_route_attach_agent_runs():
    app = FastAPI()

    @app.get("/api/qclaw/smoke")
    def qclaw_smoke():
        return {"success": True, "source": "smoke"}

    app.include_router(ai_open_router)
    app.include_router(ai_qclaw_router)
    repo = InMemoryAgentRunRepository()

    with (
        TestClient(app) as local_client,
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        wechat = local_client.post(
            "/api/ai/qclaw/wechat-gateway", json={"enabled": True}
        ).json()
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


def test_aiopen_openclaw_chat_attaches_agent_run(client):
    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.fastapi_routes.ai_open.openclaw_chat_proxy",
            return_value=({"success": True, "data": {"answer": "pong"}}, 200),
        ),
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        resp = client.post(
            "/api/aiopen/openclaw/chat",
            json={"message": "hello", "user_id": "aiopen-user"},
        )

    assert resp.status_code == 200
    body = resp.json()
    run_id = body["run_id"]
    assert body["agent_run_id"] == run_id
    assert body["data"]["run_id"] == run_id
    assert body["data"]["answer"] == "pong"

    run = repo.get(run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.user_id == "aiopen-user"
    assert run.intent == "external_openclaw_chat"
    assert run.metadata["channel"] == "aiopen_openclaw"
    assert run.metadata["source"] == "aiopen"
    assert run.metadata["runtime_context"]["route"] == "/api/aiopen/openclaw/chat"


def test_qclaw_openclaw_chat_attaches_agent_run(client):
    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.fastapi_routes.ai_qclaw.openclaw_chat_proxy",
            return_value=({"success": True, "data": {"answer": "pong"}}, 200),
        ),
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        resp = client.post(
            "/api/ai/qclaw/openclaw/chat",
            json={"message": "hello", "user_id": "qclaw-user"},
        )

    assert resp.status_code == 200
    body = resp.json()
    run_id = body["run_id"]
    assert body["agent_run_id"] == run_id
    assert body["data"]["run_id"] == run_id
    assert body["data"]["answer"] == "pong"

    run = repo.get(run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.user_id == "qclaw-user"
    assert run.intent == "external_openclaw_chat"
    assert run.metadata["channel"] == "qclaw_openclaw"
    assert run.metadata["source"] == "qclaw"
    assert run.metadata["runtime_context"]["route"] == "/api/ai/qclaw/openclaw/chat"


def test_screen_ws_command_roundtrip(client):
    """screen 端 WS 收到指令并回执 → ui 工具拿到结果。"""
    AIOPEN_STATE["remote_control_enabled"] = True
    with client.websocket_connect("/api/aiopen/ws?session_id=test_screen&label=pytest") as ws:
        hello = ws.receive_json()
        assert hello == {"type": "hello", "session_id": "test_screen"}

        sessions = client.post(
            "/api/aiopen/invoke", json={"tool": "ui_sessions", "args": {}}
        ).json()
        assert any(s["session_id"] == "test_screen" for s in sessions["sessions"])


def test_aiopen_source_alias():
    from app.utils.ai_helpers import is_qclaw_source

    assert is_qclaw_source("aiopen")
    assert is_qclaw_source("qclaw")
    assert is_qclaw_source("lobster")
    assert not is_qclaw_source("pro")
