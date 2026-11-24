"""Tests for app.application.aiopen.service."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.aiopen.service import (
    _UI_ACTIONS,
    AIOPEN_PRODUCT_NAME,
    AIOPEN_PRODUCT_TAGLINE,
    AIOPEN_STATE,
    MCP_DEFAULT_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSIONS,
    MCP_SERVER_NAME,
    TOOL_DEFINITIONS,
    _env_api_key,
    _tool_api_catalog,
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
    revoke_api_key,
    verify_api_key,
)
from app.infrastructure.aiopen.principal_context import execution_context_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

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
    def test_no_keys_configured_denies_access(self):
        saved = AIOPEN_STATE.pop("runtime_keys", None)
        try:
            with patch.dict(os.environ, {}, clear=True):
                assert verify_api_key(None) is False
                assert verify_api_key("anything") is False
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
    @pytest.mark.parametrize(
        ("receipt", "expected"),
        [
            ({"success": False, "execution_state": "queued"}, "排队中"),
            ({"success": False, "pending_approval": True}, "等待审批"),
            ({"success": True, "execution_state": "unknown"}, "待核对"),
            ({"success": True, "reconciliation_required": True}, "待核对"),
            ({"success": True, "execution_state": "completed"}, "已完成"),
            ({"success": False, "execution_state": "failed"}, "未完成"),
        ],
    )
    def test_operation_receipt_preserves_state_and_correlation(self, receipt, expected):
        text = format_tool_result_text(
            "operation_call",
            {"operation_id": "capability.ocr.request", "run_id": "original-run", **receipt},
        )
        assert expected in text
        assert "run_id: original-run" in text
        assert "HTTP" not in text

    def test_api_catalog_success(self):
        result = {
            "success": True,
            "capabilities": [
                {"capability_id": "ocr.request", "description": "Request OCR"},
            ],
        }
        text = format_tool_result_text("api_catalog", result)
        assert "1 项" in text
        assert "ocr.request" in text

    def test_api_catalog_empty_routes(self):
        text = format_tool_result_text("api_catalog", {"success": True, "capabilities": []})
        assert "0 项" in text

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

    def test_ui_snapshot_uses_ref_and_state(self):
        result = {
            "success": True,
            "elements": [
                {"ref": "e1", "role": "textbox", "name": "手机号", "state": {"disabled": True}},
            ],
            "truncated": True,
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "e1" in text
        assert "手机号" in text
        assert "disabled" in text
        assert "截断" in text

    def test_ui_verify_lists_checks(self):
        result = {
            "success": False,
            "checks": [
                {"check": "元素存在", "ok": True, "detail": "ref=e1"},
                {"check": "控件值", "ok": False, "detail": "期望「A」，实际「B」"},
            ],
        }
        text = format_tool_result_text("ui_verify", result)
        assert "未通过" in text
        assert "✓ 元素存在" in text
        assert "✗ 控件值" in text

    def test_ui_wait_and_screenshot(self):
        assert "等待完成" in format_tool_result_text(
            "ui_wait", {"success": True, "waited_ms": 320, "matched": "元素出现"}
        )
        assert "等待超时" in format_tool_result_text(
            "ui_wait", {"success": False, "message": "等待超时（5000ms）"}
        )
        shot = format_tool_result_text(
            "ui_screenshot",
            {"success": True, "width": 800, "height": 600, "bytes": 2048, "target": "ref=e1"},
        )
        assert "800×600" in shot
        assert "data_url" not in shot

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
        from app.infrastructure.mods.manifest import host_xcagi_version

        assert m["version"] == host_xcagi_version()
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
    def test_unbound_catalog_is_denied(self):
        result = _tool_api_catalog()
        assert result["success"] is False
        assert result["error_code"] == "capability_discovery_denied"
        assert result["capabilities"] == []

    def test_catalog_uses_current_account_grants(self, trusted_actor):
        actor = trusted_actor(permissions=["tool.ocr.request"])
        with execution_context_scope(actor.context):
            result = _tool_api_catalog()
        assert result["success"] is True
        visible = {item["capability_id"] for item in result["capabilities"]}
        assert "ocr.request" in visible
        assert "business_db.write" not in visible
        assert "employee.execute" not in visible
        assert result["authority"] == "ToolActionSpecV2"


# ── _tool_chat ────────────────────────────────────────────────


class TestToolChat:
    def test_empty_message_returns_error(self, trusted_actor):
        with execution_context_scope(trusted_actor().context):
            result = _tool_chat(MagicMock(), {"message": "", "request_id": "empty-chat"})
        assert result["success"] is False
        assert result["code"] == "INVALID_ARGUMENT"


# ── invoke_tool ───────────────────────────────────────────────


class TestInvokeTool:
    @pytest.mark.asyncio
    async def test_api_catalog(self):
        result = await invoke_tool("api_catalog", {}, MagicMock())
        assert result["success"] is False
        assert result["error_code"] == "capability_discovery_denied"

    @pytest.mark.asyncio
    async def test_removed_api_call_has_no_http_fallback(self):
        with patch("starlette.testclient.TestClient") as factory:
            result = await invoke_tool("api_call", {"path": "/api/products"}, MagicMock())
        assert result["success"] is False
        assert result["code"] == "UNKNOWN_TOOL"
        factory.assert_not_called()

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
            with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
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
        assert result["success"] is False
        assert result["error_code"] == "capability_discovery_denied"

    @pytest.mark.asyncio
    async def test_empty_name(self):
        result = await invoke_tool("", {}, MagicMock())
        assert result["success"] is False


# ── Constants ─────────────────────────────────────────────────


class TestConstants:
    def test_mcp_protocol_versions(self):
        assert isinstance(MCP_PROTOCOL_VERSIONS, tuple)
        assert MCP_DEFAULT_PROTOCOL_VERSION in MCP_PROTOCOL_VERSIONS

    def test_tool_definitions_count(self):
        names = {tool["name"] for tool in TOOL_DEFINITIONS}
        assert len(names) == len(TOOL_DEFINITIONS)
        assert {
            "api_catalog",
            "knowledge_search",
            "operation_describe",
            "operation_call",
            "chat",
            "capability_loop",
            "ui_sessions",
            "ui_snapshot",
            "ui_navigate",
            "ui_click",
            "ui_type",
            "ui_select",
            "ui_upload",
            "ui_wait",
            "ui_verify",
            "ui_screenshot",
            "ui_scroll",
        } <= names

    def test_ui_actions_mapping(self):
        assert _UI_ACTIONS == {
            "ui_snapshot": "snapshot",
            "ui_navigate": "navigate",
            "ui_click": "click",
            "ui_type": "type",
            "ui_select": "select",
            "ui_upload": "upload",
            "ui_wait": "wait",
            "ui_verify": "verify",
            "ui_screenshot": "screenshot",
            "ui_scroll": "scroll",
        }

    def test_ui_tools_accept_ref(self):
        by_name = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
        for name in ("ui_click", "ui_type", "ui_select", "ui_upload", "ui_scroll"):
            assert "ref" in by_name[name]["inputSchema"]["properties"]
        assert "ref" in by_name["ui_snapshot"]["description"]

    def test_aiopen_state_structure(self):
        assert "whitelist" in AIOPEN_STATE
        assert "openclaw_base" in AIOPEN_STATE
        assert "remote_control_enabled" in AIOPEN_STATE
        assert "runtime_keys" in AIOPEN_STATE
