"""AIOPEN 开放平台（原 Qclaw龙虾生态 toA 升级）端到端测试。

覆盖：manifest 公开访问、invoke 鉴权 401 / 白名单 403、
MCP JSON-RPC（initialize → tools/list → tools/call）、
旧 ``/api/ai/qclaw/*`` URL 兼容与状态共享。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    tool_names = {t["name"] for t in data["tools"]}
    assert {"api_catalog", "api_call", "chat", "ui_snapshot", "ui_click", "ui_type"} <= tool_names


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
    assert aiopen_service.list_api_keys() == []


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

    ping = client.post(
        "/api/aiopen/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "ping"}
    ).json()
    assert ping["result"] == {}

    unknown = client.post(
        "/api/aiopen/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "bogus/method"}
    ).json()
    assert unknown["error"]["code"] == -32601


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
