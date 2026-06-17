"""Tests for app.application.aiopen.service."""
from __future__ import annotations

import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.aiopen.service import (
    AIOPEN_PRODUCT_NAME,
    AIOPEN_PRODUCT_TAGLINE,
    AIOPEN_STATE,
    MCP_DEFAULT_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSIONS,
    MCP_SERVER_NAME,
    TOOL_DEFINITIONS,
    _UI_ACTIONS,
    _env_api_key,
    _tool_api_catalog,
    _tool_api_call,
    _tool_chat,
    aiopen_manifest,
    build_aiopen_guide,
    build_cursor_deeplink,
    build_mcp_install_bundle,
    build_mcp_remote_config,
    build_mcp_stdio_config,
    build_mcp_url_config,
    format_tool_result_text,
    generate_api_key,
    invoke_tool,
    list_api_keys,
    openclaw_chat_proxy,
    revoke_api_key,
    verify_api_key,
)


# ── API Key 鉴权 ──────────────────────────────────────────────


class TestEnvApiKey:
    def test_returns_env_value(self):
        with patch.dict(os.environ, {"AIOPEN_API_KEY": "mykey"}):
            assert _env_api_key() == "mykey"

    def test_returns_empty_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if present
            os.environ.pop("AIOPEN_API_KEY", None)
            assert _env_api_key() == ""

    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"AIOPEN_API_KEY": "  key123  "}):
            assert _env_api_key() == "key123"


class TestVerifyApiKey:
    def test_no_keys_configured_allows_access(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.pop("runtime_keys", None)
        try:
            assert verify_api_key(None) is True
            assert verify_api_key("anything") is True
        finally:
            if saved is not None:
                AIOPEN_STATE["runtime_keys"] = saved

    def test_env_key_match(self):
        with patch.dict(os.environ, {"AIOPEN_API_KEY": "envkey123"}):
            assert verify_api_key("envkey123") is True

    def test_env_key_mismatch(self):
        with patch.dict(os.environ, {"AIOPEN_API_KEY": "envkey123"}):
            saved = AIOPEN_STATE.pop("runtime_keys", None)
            try:
                assert verify_api_key("wrong") is False
            finally:
                if saved is not None:
                    AIOPEN_STATE["runtime_keys"] = saved

    def test_empty_provided_with_keys_configured(self):
        with patch.dict(os.environ, {"AIOPEN_API_KEY": "envkey123"}):
            saved = AIOPEN_STATE.pop("runtime_keys", None)
            try:
                assert verify_api_key("") is False
                assert verify_api_key(None) is False
            finally:
                if saved is not None:
                    AIOPEN_STATE["runtime_keys"] = saved

    def test_runtime_key_match(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["rt_key_abc"] = {"label": "test", "created_at": 1.0}
        try:
            assert verify_api_key("rt_key_abc") is True
        finally:
            saved.pop("rt_key_abc", None)

    def test_runtime_key_mismatch(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["rt_key_xyz"] = {"label": "test", "created_at": 1.0}
        try:
            assert verify_api_key("nonexistent") is False
        finally:
            saved.pop("rt_key_xyz", None)


class TestGenerateApiKey:
    def test_generates_key_with_default_label(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        before = len(saved)
        result = generate_api_key()
        assert result["key"].startswith("aiopen_")
        assert result["label"] == "未命名"
        assert "created_at" in result
        assert len(saved) == before + 1
        # cleanup
        saved.pop(result["key"], None)

    def test_generates_key_with_custom_label(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        result = generate_api_key("my-label")
        assert result["label"] == "my-label"
        saved.pop(result["key"], None)

    def test_empty_label_uses_default(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        result = generate_api_key("")
        assert result["label"] == "未命名"
        saved.pop(result["key"], None)


class TestRevokeApiKey:
    def test_revoke_existing_key(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["test_key"] = {"label": "test", "created_at": 1.0}
        assert revoke_api_key("test_key") is True
        assert "test_key" not in saved

    def test_revoke_nonexistent_key(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        assert revoke_api_key("nonexistent") is False

    def test_revoke_empty_key(self):
        assert revoke_api_key("") is False


class TestListApiKeys:
    def test_no_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.pop("runtime_keys", None)
        try:
            AIOPEN_STATE["runtime_keys"] = {}
            result = list_api_keys()
            assert result == []
        finally:
            if saved is not None:
                AIOPEN_STATE["runtime_keys"] = saved

    def test_env_key_listed(self):
        with patch.dict(os.environ, {"AIOPEN_API_KEY": "envkey"}):
            saved = AIOPEN_STATE.pop("runtime_keys", None)
            try:
                AIOPEN_STATE["runtime_keys"] = {}
                result = list_api_keys()
                assert len(result) == 1
                assert result[0]["key_preview"] == "env:AIOPEN_API_KEY"
            finally:
                if saved is not None:
                    AIOPEN_STATE["runtime_keys"] = saved

    def test_runtime_keys_listed_with_preview(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["aiopen_abcdefghij123456"] = {"label": "test", "created_at": 1.0}
        try:
            result = list_api_keys()
            assert len(result) == 1
            assert result[0]["key_preview"].startswith("aiopen_abcde")
            assert result[0]["key_preview"].endswith("…")
        finally:
            saved.pop("aiopen_abcdefghij123456", None)


# ── MCP 配置构建 ──────────────────────────────────────────────


class TestBuildMcpUrlConfig:
    def test_basic_url(self):
        cfg = build_mcp_url_config("http://localhost:5100")
        assert cfg["url"] == "http://localhost:5100/api/aiopen/mcp"
        assert "headers" not in cfg

    def test_url_with_api_key(self):
        cfg = build_mcp_url_config("http://localhost:5100/", "mykey")
        assert cfg["url"] == "http://localhost:5100/api/aiopen/mcp"
        assert cfg["headers"]["X-AIOPEN-Key"] == "mykey"

    def test_strips_trailing_slash(self):
        cfg = build_mcp_url_config("http://example.com///")
        assert cfg["url"] == "http://example.com/api/aiopen/mcp"

    def test_empty_base_url(self):
        cfg = build_mcp_url_config("")
        assert cfg["url"] == "/api/aiopen/mcp"


class TestBuildMcpStdioConfig:
    def test_basic_config(self):
        cfg = build_mcp_stdio_config("http://localhost:5100")
        assert cfg["command"] == "python3"
        assert "args" in cfg
        assert cfg["env"]["AIOPEN_BASE_URL"] == "http://localhost:5100"
        assert "AIOPEN_API_KEY" not in cfg["env"]

    def test_with_api_key(self):
        cfg = build_mcp_stdio_config("http://localhost:5100", "mykey")
        assert cfg["env"]["AIOPEN_API_KEY"] == "mykey"


class TestBuildMcpRemoteConfig:
    def test_basic_config(self):
        cfg = build_mcp_remote_config("http://localhost:5100")
        assert cfg["command"] == "npx"
        assert "-y" in cfg["args"]
        assert "mcp-remote" in cfg["args"]
        assert "http://localhost:5100/api/aiopen/mcp" in cfg["args"]

    def test_with_api_key(self):
        cfg = build_mcp_remote_config("http://localhost:5100", "mykey")
        assert "--header" in cfg["args"]
        assert "X-AIOPEN-Key:mykey" in cfg["args"]


class TestBuildCursorDeeplink:
    def test_generates_valid_deeplink(self):
        cfg = {"url": "http://localhost/api/aiopen/mcp"}
        link = build_cursor_deeplink("test-server", cfg)
        assert link.startswith("cursor://anysphere.cursor-deeplink/mcp/install?")
        assert "name=test-server" in link
        assert "config=" in link

    def test_deeplink_config_is_valid_base64_json(self):
        cfg = {"url": "http://localhost/api/aiopen/mcp"}
        link = build_cursor_deeplink("test-server", cfg)
        # Extract config param
        import urllib.parse
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)
        config_b64 = params["config"][0]
        decoded = json.loads(base64.b64decode(config_b64))
        assert decoded == cfg


class TestBuildMcpInstallBundle:
    def test_returns_complete_bundle(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        assert bundle["server_name"] == MCP_SERVER_NAME
        assert bundle["mcp_url"] == "http://localhost:5100/api/aiopen/mcp"
        assert "clients" in bundle
        assert len(bundle["clients"]) >= 5
        assert "methods" in bundle
        assert "url" in bundle["methods"]
        assert "mcp_remote" in bundle["methods"]
        assert "stdio" in bundle["methods"]

    def test_clients_have_required_fields(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        for client in bundle["clients"]:
            assert "id" in client
            assert "name" in client
            assert "transport" in client
            assert "mcp_json" in client
            assert "config" in client

    def test_cursor_client_has_deeplink(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        cursor = next(c for c in bundle["clients"] if c["id"] == "cursor")
        assert "cursor_deeplink" in cursor
        assert "web_install_url" in cursor


# ── format_tool_result_text ───────────────────────────────────


class TestFormatToolResultText:
    def test_api_catalog_success(self):
        result = {
            "success": True,
            "routes": [
                {"path": "/api/products", "enabled": True},
                {"path": "/api/disabled", "enabled": False},
            ],
        }
        text = format_tool_result_text("api_catalog", result)
        assert "1/2 已启用" in text
        assert "✓ /api/products" in text
        assert "· /api/disabled" in text

    def test_api_catalog_empty_routes(self):
        text = format_tool_result_text("api_catalog", {"success": True, "routes": []})
        assert "0/0 已启用" in text

    def test_api_call_success(self):
        result = {
            "success": True,
            "path": "/api/products",
            "method": "GET",
            "status_code": 200,
            "data": {"items": []},
        }
        text = format_tool_result_text("api_call", result)
        assert "API 调用成功" in text
        assert "GET /api/products" in text
        assert "HTTP 200" in text

    def test_api_call_failure(self):
        result = {"success": False, "path": "/api/x", "method": "POST", "message": "forbidden"}
        text = format_tool_result_text("api_call", result)
        assert "API 调用失败" in text

    def test_api_call_large_data_truncated(self):
        result = {
            "success": True,
            "path": "/api/big",
            "method": "GET",
            "status_code": 200,
            "data": {"items": ["x" * 5000]},
        }
        text = format_tool_result_text("api_call", result)
        assert "truncated" in text

    def test_chat_success(self):
        result = {"success": True, "data": {"reply": "你好世界"}}
        text = format_tool_result_text("chat", result)
        assert "XCAGI 助手回复" in text
        assert "你好世界" in text

    def test_chat_failure(self):
        result = {"success": False, "message": "timeout"}
        text = format_tool_result_text("chat", result)
        assert "对话失败" in text

    def test_chat_data_with_message_key(self):
        result = {"success": True, "data": {"message": "hello"}}
        text = format_tool_result_text("chat", result)
        assert "hello" in text

    def test_chat_data_with_content_key(self):
        result = {"success": True, "data": {"content": "world"}}
        text = format_tool_result_text("chat", result)
        assert "world" in text

    def test_ui_sessions_empty(self):
        text = format_tool_result_text("ui_sessions", {"success": True, "sessions": []})
        assert "无在线虚拟光标会话" in text

    def test_ui_sessions_with_sessions(self):
        result = {
            "success": True,
            "sessions": [
                {"session_id": "s1", "label": "前端1"},
            ],
        }
        text = format_tool_result_text("ui_sessions", result)
        assert "1 个" in text
        assert "s1" in text

    def test_ui_snapshot_success(self):
        result = {
            "success": True,
            "url": "http://x.com/page",
            "title": "My Page",
            "elements": [
                {"selector": "#btn", "text": "Click", "role": "button"},
            ],
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "My Page" in text
        assert "http://x.com/page" in text
        assert "1 个" in text
        assert "#btn" in text

    def test_ui_snapshot_failure(self):
        result = {"success": False, "message": "no session"}
        text = format_tool_result_text("ui_snapshot", result)
        assert "页面快照失败" in text

    def test_ui_action_success(self):
        result = {"success": True, "message": "clicked"}
        text = format_tool_result_text("ui_click", result)
        assert "clicked" in text

    def test_ui_action_failure(self):
        result = {"success": False, "message": "timeout"}
        text = format_tool_result_text("ui_type", result)
        assert "ui_type 失败" in text

    def test_ui_action_with_extra_fields(self):
        result = {"success": True, "message": "done", "extra_key": "extra_val"}
        text = format_tool_result_text("ui_navigate", result)
        assert "extra_key" in text

    def test_unknown_tool_failure(self):
        result = {"success": False, "message": "err", "code": "X"}
        text = format_tool_result_text("unknown_tool", result)
        assert "unknown_tool 失败" in text

    def test_unknown_tool_success(self):
        result = {"success": True, "data": "ok"}
        text = format_tool_result_text("custom_tool", result)
        # Falls through to json.dumps
        assert "ok" in text

    def test_empty_tool_name(self):
        text = format_tool_result_text("", {"success": True, "data": "x"})
        assert "x" in text


# ── aiopen_manifest ───────────────────────────────────────────


class TestAiopenManifest:
    def test_structure(self):
        m = aiopen_manifest()
        assert m["name"] == AIOPEN_PRODUCT_NAME
        assert m["tagline"] == AIOPEN_PRODUCT_TAGLINE
        assert m["version"] == "10.0.0"
        assert "protocol" in m
        assert "tools" in m
        assert len(m["tools"]) == len(TOOL_DEFINITIONS)

    def test_tools_have_required_keys(self):
        m = aiopen_manifest()
        for tool in m["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


# ── build_aiopen_guide ────────────────────────────────────────


class TestBuildAiopenGuide:
    def test_returns_guide_structure(self):
        guide = build_aiopen_guide("http://localhost:5100")
        assert guide["success"] is True
        assert guide["base_url"] == "http://localhost:5100"
        assert "endpoints" in guide
        assert guide["endpoints"]["mcp"] == "http://localhost:5100/api/aiopen/mcp"
        assert "markdown" in guide
        assert "install" in guide
        assert "prompt_for_user" in guide

    def test_guide_markdown_contains_key_info(self):
        guide = build_aiopen_guide("http://localhost:5100")
        md = guide["markdown"]
        assert AIOPEN_PRODUCT_NAME in md
        assert "MCP" in md
        assert "X-AIOPEN-Key" in md

    def test_guide_strips_trailing_slash(self):
        guide = build_aiopen_guide("http://localhost:5100///")
        assert guide["base_url"] == "http://localhost:5100"


# ── _tool_api_catalog ─────────────────────────────────────────


class TestToolApiCatalog:
    def test_returns_whitelist_routes(self):
        result = _tool_api_catalog()
        assert result["success"] is True
        assert isinstance(result["routes"], list)
        for r in result["routes"]:
            assert "path" in r
            assert "enabled" in r


# ── _tool_api_call ────────────────────────────────────────────


class TestToolApiCall:
    def test_empty_path_returns_error(self):
        result = _tool_api_call(MagicMock(), {"path": ""})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_non_whitelisted_path_returns_error(self):
        saved_whitelist = AIOPEN_STATE.get("whitelist", {})
        AIOPEN_STATE["whitelist"] = {"/api/products": True}
        try:
            result = _tool_api_call(MagicMock(), {"path": "/api/forbidden"})
            assert result["success"] is False
            assert "未在 AIOPEN 白名单启用" in result["message"]
        finally:
            AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_whitelisted_get_call(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["success"] is True
                assert result["status_code"] == 200
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_whitelisted_post_call(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(
                    MagicMock(), {"path": "/api/products", "method": "POST", "body": {"name": "x"}}
                )
                assert result["success"] is True
                assert result["method"] == "POST"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_api_call_json_parse_failure(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "plain text response"
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["data"]["raw"] == "plain text response"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_api_call_recoverable_error(self):
        with patch("starlette.testclient.TestClient", side_effect=ConnectionError("refused")):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["success"] is False
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist


# ── _tool_chat ────────────────────────────────────────────────


class TestToolChat:
    def test_empty_message_returns_error(self):
        result = _tool_chat(MagicMock(), {"message": ""})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_valid_message_calls_api(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"reply": "hello"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/ai/unified_chat": True}
            try:
                result = _tool_chat(MagicMock(), {"message": "hi"})
                assert result["success"] is True
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist


# ── invoke_tool ───────────────────────────────────────────────


class TestInvokeTool:
    @pytest.mark.asyncio
    async def test_api_catalog(self):
        result = await invoke_tool("api_catalog", {}, MagicMock())
        assert result["success"] is True
        assert "routes" in result

    @pytest.mark.asyncio
    async def test_api_call(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = await invoke_tool("api_call", {"path": "/api/products"}, MagicMock())
                assert result["success"] is True
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    @pytest.mark.asyncio
    async def test_chat(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"reply": "hi"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/ai/unified_chat": True}
            try:
                result = await invoke_tool("chat", {"message": "hi"}, MagicMock())
                assert result["success"] is True
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    @pytest.mark.asyncio
    async def test_ui_sessions(self):
        result = await invoke_tool("ui_sessions", {}, MagicMock())
        assert result["success"] is True
        assert "sessions" in result

    @pytest.mark.asyncio
    async def test_ui_action_remote_control_disabled(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = False
        try:
            result = await invoke_tool("ui_click", {"selector": "#btn"}, MagicMock())
            assert result["success"] is False
            assert "REMOTE_CONTROL_DISABLED" in result.get("code", "")
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_action_dispatches_to_cursor_hub(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            with patch(
                "app.application.aiopen.service.aiopen_cursor_hub"
            ) as mock_hub:
                mock_hub.dispatch = AsyncMock(return_value={"success": True})
                result = await invoke_tool(
                    "ui_click", {"selector": "#btn", "session_id": "s1"}, MagicMock()
                )
                assert result["success"] is True
                mock_hub.dispatch.assert_called_once()
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await invoke_tool("nonexistent_tool", {}, MagicMock())
        assert result["success"] is False
        assert "UNKNOWN_TOOL" in result.get("code", "")

    @pytest.mark.asyncio
    async def test_none_args_treated_as_empty_dict(self):
        result = await invoke_tool("api_catalog", None, MagicMock())
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_empty_name(self):
        result = await invoke_tool("", {}, MagicMock())
        assert result["success"] is False


# ── openclaw_chat_proxy ───────────────────────────────────────


class TestOpenclawChatProxy:
    def test_success(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"reply": "hello"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is True
            assert status == 200
            assert payload["data"]["reply"] == "hello"

    def test_http_error(self):
        import urllib.error
        err = urllib.error.HTTPError("http://x", 500, "Server Error", {}, None)
        err.read = MagicMock(return_value=b"internal error")
        with patch("app.application.aiopen.service.urllib.request.urlopen", side_effect=err):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is False
            assert status == 502

    def test_connection_error(self):
        with patch(
            "app.application.aiopen.service.urllib.request.urlopen",
            side_effect=ConnectionError("refused"),
        ):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is False
            assert status == 502

    def test_uses_openclaw_base_from_state(self):
        saved = AIOPEN_STATE.get("openclaw_base")
        AIOPEN_STATE["openclaw_base"] = "http://custom:9999"
        try:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                openclaw_chat_proxy("hi")
                call_args = mock_urlopen.call_args
                req = call_args[0][0]
                assert req.full_url == "http://custom:9999/api/chat"
        finally:
            AIOPEN_STATE["openclaw_base"] = saved


# ── Constants ─────────────────────────────────────────────────


class TestConstants:
    def test_mcp_protocol_versions(self):
        assert isinstance(MCP_PROTOCOL_VERSIONS, tuple)
        assert MCP_DEFAULT_PROTOCOL_VERSION in MCP_PROTOCOL_VERSIONS

    def test_tool_definitions_count(self):
        assert len(TOOL_DEFINITIONS) == 9

    def test_ui_actions_mapping(self):
        assert "ui_snapshot" in _UI_ACTIONS
        assert "ui_navigate" in _UI_ACTIONS
        assert "ui_click" in _UI_ACTIONS
        assert "ui_type" in _UI_ACTIONS
        assert "ui_scroll" in _UI_ACTIONS

    def test_aiopen_state_structure(self):
        assert "whitelist" in AIOPEN_STATE
        assert "openclaw_base" in AIOPEN_STATE
        assert "remote_control_enabled" in AIOPEN_STATE
        assert "runtime_keys" in AIOPEN_STATE
