"""Extension tests for app.application.aiopen.service — coverage gap filling.

These tests target branches not covered by ``test_aiopen_service.py``:
- ``format_tool_result_text`` edge cases (>40 elements, non-dict items, fallback keys,
  empty data, non-dict chat data, detail fallback, code fallback for unknown tool).
- ``_tool_api_call`` POST with body, status >= 500, TypeError on json parse.
- ``invoke_tool`` ui_action with/without session_id, ui_sessions remote_control flag.
- ``openclaw_chat_proxy`` non-JSON body, empty body.
- ``_repo_stdio_bridge_path`` returns absolute path.
- ``build_mcp_install_bundle`` web_install_url / install_mode variants.
- ``build_aiopen_guide`` remote_control_enabled / screen_sessions_online / instructions_for_ai.
- ``verify_api_key`` whitespace stripping.
- ``generate_api_key`` whitespace label.
- ``revoke_api_key`` whitespace key.
- ``list_api_keys`` env + runtime combined.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.aiopen.service import (
    AIOPEN_STATE,
    MCP_SERVER_NAME,
    TOOL_DEFINITIONS,
    _repo_stdio_bridge_path,
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

# ── _repo_stdio_bridge_path ───────────────────────────────────


class TestRepoStdioBridgePath:
    def test_returns_absolute_path_str(self):
        p = _repo_stdio_bridge_path()
        assert isinstance(p, str)
        assert p.endswith("aiopen_mcp_stdio.py")
        # Path is absolute
        assert Path(p).is_absolute()

    def test_path_located_in_scripts_dev(self):
        p = _repo_stdio_bridge_path()
        # parents[3] of service.py = repo root; bridge under scripts/dev/
        parts = Path(p).parts
        assert "scripts" in parts
        assert "dev" in parts


# ── verify_api_key — whitespace handling ──────────────────────


class TestVerifyApiKeyExt:
    def test_strips_whitespace_from_provided(self):
        with patch.dict("os.environ", {"AIOPEN_API_KEY": "envkey123"}, clear=False):
            saved = AIOPEN_STATE.pop("runtime_keys", None)
            try:
                # Provided key with surrounding whitespace should still match
                assert verify_api_key("  envkey123  ") is True
            finally:
                if saved is not None:
                    AIOPEN_STATE["runtime_keys"] = saved

    def test_provided_only_whitespace_returns_false(self):
        with patch.dict("os.environ", {"AIOPEN_API_KEY": "envkey123"}, clear=False):
            saved = AIOPEN_STATE.pop("runtime_keys", None)
            try:
                # Whitespace-only provided key strips to empty -> False
                assert verify_api_key("   ") is False
            finally:
                if saved is not None:
                    AIOPEN_STATE["runtime_keys"] = saved

    def test_runtime_key_match_with_whitespace(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["rt_key_ws"] = {"label": "test", "created_at": 1.0}
        try:
            # Note: runtime key check uses `in` without stripping provided,
            # but `got = (provided or "").strip()` so whitespace is stripped.
            assert verify_api_key("  rt_key_ws  ") is True
        finally:
            saved.pop("rt_key_ws", None)


# ── generate_api_key — whitespace label ───────────────────────


class TestGenerateApiKeyExt:
    def test_whitespace_label_stripped_to_default(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        result = generate_api_key("   ")
        try:
            assert result["label"] == "未命名"
        finally:
            saved.pop(result["key"], None)

    def test_label_with_surrounding_whitespace_stripped(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        result = generate_api_key("  my-label  ")
        try:
            assert result["label"] == "my-label"
        finally:
            saved.pop(result["key"], None)


# ── revoke_api_key — whitespace key ───────────────────────────


class TestRevokeApiKeyExt:
    def test_revoke_key_with_whitespace(self):
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["ws_key"] = {"label": "test", "created_at": 1.0}
        try:
            # Whitespace is stripped before lookup
            assert revoke_api_key("  ws_key  ") is True
            assert "ws_key" not in saved
        finally:
            saved.pop("ws_key", None)

    def test_revoke_none_key_returns_false(self):
        assert revoke_api_key(None) is False


# ── list_api_keys — combined env + runtime ────────────────────


class TestListApiKeysExt:
    def test_env_and_runtime_keys_combined(self):
        with patch.dict("os.environ", {"AIOPEN_API_KEY": "envkey"}, clear=False):
            saved = AIOPEN_STATE.setdefault("runtime_keys", {})
            saved["aiopen_rtkey12345"] = {"label": "rt", "created_at": 2.0}
            try:
                result = list_api_keys()
                # First entry is env, second is runtime
                assert len(result) == 2
                assert result[0]["key_preview"] == "env:AIOPEN_API_KEY"
                assert result[0]["label"] == "环境变量"
                assert result[0]["created_at"] is None
                # key_preview is key[:12] + "…"
                assert result[1]["key_preview"] == "aiopen_rtkey…"
                assert result[1]["label"] == "rt"
                assert result[1]["created_at"] == 2.0
            finally:
                saved.pop("aiopen_rtkey12345", None)

    def test_runtime_key_missing_label_uses_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["aiopen_nolabel123"] = {"created_at": 3.0}  # no 'label' key
        try:
            result = list_api_keys()
            assert len(result) == 1
            assert result[0]["label"] == ""
        finally:
            saved.pop("aiopen_nolabel123", None)

    def test_runtime_key_missing_created_at_uses_none(self):
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("AIOPEN_API_KEY", None)
        saved = AIOPEN_STATE.setdefault("runtime_keys", {})
        saved["aiopen_notime12345"] = {"label": "x"}  # no 'created_at' key
        try:
            result = list_api_keys()
            assert len(result) == 1
            assert result[0]["created_at"] is None
        finally:
            saved.pop("aiopen_notime12345", None)


# ── build_mcp_url_config / stdio / remote — edge cases ────────


class TestMcpConfigExt:
    def test_url_config_none_api_key(self):
        cfg = build_mcp_url_config("http://x", None)
        assert "headers" not in cfg

    def test_url_config_whitespace_api_key(self):
        cfg = build_mcp_url_config("http://x", "  ")
        assert "headers" not in cfg

    def test_stdio_config_none_api_key(self):
        cfg = build_mcp_stdio_config("http://x", None)
        assert "AIOPEN_API_KEY" not in cfg["env"]

    def test_stdio_config_whitespace_api_key(self):
        cfg = build_mcp_stdio_config("http://x", "  ")
        assert "AIOPEN_API_KEY" not in cfg["env"]

    def test_stdio_config_empty_base_url(self):
        cfg = build_mcp_stdio_config("", "mykey")
        assert cfg["env"]["AIOPEN_BASE_URL"] == ""
        assert cfg["env"]["AIOPEN_API_KEY"] == "mykey"

    def test_remote_config_none_api_key(self):
        cfg = build_mcp_remote_config("http://x", None)
        assert "--header" not in cfg["args"]

    def test_remote_config_whitespace_api_key(self):
        cfg = build_mcp_remote_config("http://x", "  ")
        assert "--header" not in cfg["args"]

    def test_remote_config_empty_base_url(self):
        cfg = build_mcp_remote_config("", "mykey")
        # root becomes "" so url is "/api/aiopen/mcp"
        assert "/api/aiopen/mcp" in cfg["args"]
        assert "--header" in cfg["args"]


# ── build_cursor_deeplink — special chars ─────────────────────


class TestBuildCursorDeeplinkExt:
    def test_server_name_with_special_chars_is_quoted(self):
        cfg = {"url": "http://x/mcp"}
        link = build_cursor_deeplink("my server/name", cfg)
        # quote with safe='' encodes spaces and slashes
        assert "name=my%20server%2Fname" in link

    def test_config_with_unicode_is_preserved(self):
        cfg = {"url": "http://x/中文"}
        link = build_cursor_deeplink("srv", cfg)
        # Should not raise; link is well-formed
        assert link.startswith("cursor://anysphere.cursor-deeplink/mcp/install?")


# ── build_mcp_install_bundle — fields ─────────────────────────


class TestBuildMcpInstallBundleExt:
    def test_recommended_field_is_url(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        assert bundle["recommended"] == "url"

    def test_methods_have_cursor_deeplink(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        for method_key in ("url", "mcp_remote", "stdio"):
            assert "cursor_deeplink" in bundle["methods"][method_key]

    def test_cursor_client_has_web_install_url(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        cursor = next(c for c in bundle["clients"] if c["id"] == "cursor")
        assert cursor["install_mode"] == "deeplink"
        assert cursor["web_install_url"].startswith("https://cursor.com/en/install-mcp?")

    def test_vscode_client_install_mode(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        vscode = next(c for c in bundle["clients"] if c["id"] == "vscode")
        assert vscode["install_mode"] == "vscode"

    def test_client_without_deeplink_has_no_field(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        # generic client should not have cursor_deeplink or web_install_url
        generic = next(c for c in bundle["clients"] if c["id"] == "generic")
        assert "cursor_deeplink" not in generic
        assert "web_install_url" not in generic

    def test_mcp_config_template_uses_url_cfg(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        template = bundle["mcp_config_template"]
        assert MCP_SERVER_NAME in template["mcpServers"]
        assert "url" in template["mcpServers"][MCP_SERVER_NAME]

    def test_methods_url_has_web_install_url(self):
        bundle = build_mcp_install_bundle("http://localhost:5100")
        assert "web_install_url" in bundle["methods"]["url"]

    def test_empty_base_url(self):
        bundle = build_mcp_install_bundle("")
        assert bundle["mcp_url"] == "/api/aiopen/mcp"


# ── format_tool_result_text — gap branches ────────────────────


class TestFormatToolResultTextExt:
    def test_api_catalog_non_dict_route_skipped(self):
        result = {
            "success": True,
            "routes": [
                "not-a-dict",  # should be skipped
                {"path": "/api/x", "enabled": True},
                42,  # should be skipped
            ],
        }
        text = format_tool_result_text("api_catalog", result)
        assert "1/3 已启用" in text
        assert "/api/x" in text

    def test_api_catalog_route_missing_path(self):
        result = {
            "success": True,
            "routes": [{"enabled": True}],  # no 'path' key
        }
        text = format_tool_result_text("api_catalog", result)
        # path defaults to ""
        assert "✓ " in text

    def test_api_catalog_routes_not_list(self):
        result = {"success": True, "routes": "not-a-list"}
        text = format_tool_result_text("api_catalog", result)
        # routes becomes []
        assert "0/0 已启用" in text

    def test_api_call_data_none_returns_empty(self):
        result = {
            "success": True,
            "path": "/api/x",
            "method": "GET",
            "status_code": 204,
            "data": None,
        }
        text = format_tool_result_text("api_call", result)
        assert "(empty)" in text

    def test_api_call_missing_status_code_defaults_to_question(self):
        result = {
            "success": True,
            "path": "/api/x",
            "method": "GET",
            "data": {"a": 1},
        }
        text = format_tool_result_text("api_call", result)
        assert "HTTP ?" in text

    def test_api_call_missing_method_defaults_to_get(self):
        result = {
            "success": True,
            "path": "/api/x",
            "status_code": 200,
            "data": {"a": 1},
        }
        text = format_tool_result_text("api_call", result)
        assert "GET /api/x" in text

    def test_api_call_failure_missing_message(self):
        result = {"success": False, "path": "/api/x", "method": "GET"}
        text = format_tool_result_text("api_call", result)
        # message defaults to ""
        assert "API 调用失败" in text

    def test_chat_non_dict_data_falls_back_to_result(self):
        # When data is not a dict, `data = result` (the whole dict)
        result = {"success": True, "data": "not-a-dict"}
        text = format_tool_result_text("chat", result)
        # reply stays empty, so falls back to json.dumps(data)
        assert "XCAGI 助手回复" in text

    def test_chat_dict_data_no_reply_keys(self):
        result = {"success": True, "data": {"other": "value"}}
        text = format_tool_result_text("chat", result)
        # No reply/message/content keys, so json.dumps fallback
        assert "XCAGI 助手回复" in text
        assert "other" in text

    def test_chat_empty_reply_falls_back_to_json(self):
        result = {"success": True, "data": {"reply": ""}}
        text = format_tool_result_text("chat", result)
        assert "XCAGI 助手回复" in text

    def test_chat_failure_missing_message(self):
        result = {"success": False}
        text = format_tool_result_text("chat", result)
        assert "对话失败" in text

    def test_ui_sessions_non_dict_session_skipped(self):
        result = {
            "success": True,
            "sessions": [
                "not-a-dict",  # skipped
                {"session_id": "s1", "label": "L1"},
            ],
        }
        text = format_tool_result_text("ui_sessions", result)
        assert "2 个" in text  # count is len(sessions)
        assert "s1" in text

    def test_ui_sessions_missing_session_id_defaults_question(self):
        result = {
            "success": True,
            "sessions": [{"label": "L1"}],  # no session_id
        }
        text = format_tool_result_text("ui_sessions", result)
        assert "?" in text

    def test_ui_sessions_missing_label_defaults(self):
        result = {
            "success": True,
            "sessions": [{"session_id": "s1"}],  # no label
        }
        text = format_tool_result_text("ui_sessions", result)
        assert "XCAGI 前端" in text

    def test_ui_snapshot_more_than_40_elements(self):
        elements = [{"selector": f"#e{i}", "text": f"t{i}", "role": "btn"} for i in range(45)]
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": elements,
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "45 个" in text
        assert "另有 5 个元素" in text

    def test_ui_snapshot_exactly_40_elements_no_overflow_message(self):
        elements = [{"selector": f"#e{i}", "text": f"t{i}", "role": "btn"} for i in range(40)]
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": elements,
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "40 个" in text
        assert "另有" not in text

    def test_ui_snapshot_non_dict_element_skipped(self):
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": ["not-a-dict", {"selector": "#a", "text": "A", "role": "b"}],
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "2 个" in text
        assert "#a" in text

    def test_ui_snapshot_page_url_fallback(self):
        result = {
            "success": True,
            "page_url": "http://page-url",
            "page_title": "Page Title",
            "elements": [],
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "http://page-url" in text
        assert "Page Title" in text

    def test_ui_snapshot_ref_fallback_for_selector(self):
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": [{"ref": "ref1", "text": "T1", "role": "b"}],  # no selector
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "ref1" in text

    def test_ui_snapshot_label_fallback_for_text(self):
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": [{"selector": "#a", "label": "Lab", "role": "b"}],  # no text
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "Lab" in text

    def test_ui_snapshot_tag_fallback_for_role(self):
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": [{"selector": "#a", "text": "T1", "tag": "button"}],  # no role
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "[button]" in text

    def test_ui_snapshot_text_truncated_to_60_chars(self):
        long_text = "x" * 100
        result = {
            "success": True,
            "url": "http://x",
            "title": "T",
            "elements": [{"selector": "#a", "text": long_text, "role": "b"}],
        }
        text = format_tool_result_text("ui_snapshot", result)
        # text is sliced [:60]
        assert "x" * 60 in text
        assert "x" * 61 not in text

    def test_ui_snapshot_no_url_no_title(self):
        result = {
            "success": True,
            "elements": [],
        }
        text = format_tool_result_text("ui_snapshot", result)
        assert "(无标题)" in text
        assert "(未知)" in text

    def test_ui_snapshot_failure_missing_message(self):
        result = {"success": False}
        text = format_tool_result_text("ui_snapshot", result)
        assert "页面快照失败" in text

    def test_ui_action_detail_fallback(self):
        # No 'message' key, falls back to 'detail'
        result = {"success": True, "detail": "done via detail"}
        text = format_tool_result_text("ui_click", result)
        assert "done via detail" in text

    def test_ui_action_no_message_no_detail_uses_default(self):
        result = {"success": True}
        text = format_tool_result_text("ui_click", result)
        assert "操作已执行" in text

    def test_ui_action_no_extra_fields(self):
        # Only success + message, no extra -> returns just detail string
        result = {"success": True, "message": "ok"}
        text = format_tool_result_text("ui_navigate", result)
        assert text == "ok"

    def test_ui_action_failure_missing_message(self):
        result = {"success": False}
        text = format_tool_result_text("ui_click", result)
        assert "ui_click 失败" in text

    def test_unknown_tool_failure_with_code_fallback(self):
        # No 'message' key, falls back to 'code'
        result = {"success": False, "code": "ERR_42"}
        text = format_tool_result_text("unknown_tool", result)
        assert "unknown_tool 失败" in text
        assert "ERR_42" in text

    def test_unknown_tool_failure_no_message_no_code(self):
        result = {"success": False}
        text = format_tool_result_text("unknown_tool", result)
        assert "unknown error" in text

    def test_none_tool_name(self):
        text = format_tool_result_text(None, {"success": True, "data": "x"})
        # name becomes "" -> falls through to json.dumps
        assert "x" in text

    def test_whitespace_tool_name_stripped(self):
        # "  " -> "" -> falls through to json.dumps
        text = format_tool_result_text("  ", {"success": True, "data": "x"})
        assert "x" in text


# ── _tool_api_call — gap branches ─────────────────────────────


class TestToolApiCallExt:
    def test_post_call_sets_source_default(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                _tool_api_call(MagicMock(), {"path": "/api/products", "method": "POST"})
                # Verify source was set in payload
                call_kwargs = mock_client.post.call_args
                payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
                assert payload["source"] == "aiopen"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_post_call_preserves_existing_source(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 1}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                _tool_api_call(
                    MagicMock(),
                    {"path": "/api/products", "method": "POST", "body": {"source": "custom"}},
                )
                call_kwargs = mock_client.post.call_args
                payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
                # setdefault doesn't overwrite existing
                assert payload["source"] == "custom"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_status_code_500_returns_success_false(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": "internal"}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["success"] is False
                assert result["status_code"] == 500
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_status_code_499_returns_success_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 499
        mock_resp.json.return_value = {"error": "client error"}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["success"] is True
                assert result["status_code"] == 499
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_json_type_error_falls_back_to_raw(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # TypeError on .json()
        mock_resp.json.side_effect = TypeError("not jsonable")
        mock_resp.text = "raw text"
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["data"]["raw"] == "raw text"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_body_not_dict_defaults_to_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                # body is a string, not dict -> defaults to {}
                _tool_api_call(
                    MagicMock(),
                    {"path": "/api/products", "method": "POST", "body": "not-a-dict"},
                )
                call_kwargs = mock_client.post.call_args
                payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
                # source is set to aiopen (default in empty dict)
                assert payload["source"] == "aiopen"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_method_defaults_to_get(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                # No method provided
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["method"] == "GET"
                mock_client.get.assert_called_once_with("/api/products")
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_lowercase_method_normalized(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products", "method": "post"})
                assert result["method"] == "POST"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_recoverable_error_runtime_error(self):
        with patch("starlette.testclient.TestClient", side_effect=RuntimeError("boom")):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/products": True}
            try:
                result = _tool_api_call(MagicMock(), {"path": "/api/products"})
                assert result["success"] is False
                assert "boom" in result["message"]
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist

    def test_path_with_whitespace_stripped(self):
        # path is stripped; whitespace-only -> empty -> error
        result = _tool_api_call(MagicMock(), {"path": "   "})
        assert result["success"] is False
        assert "不能为空" in result["message"]


# ── _tool_chat — gap branches ─────────────────────────────────


class TestToolChatExt:
    def test_whitespace_message_returns_error(self):
        result = _tool_chat(MagicMock(), {"message": "   "})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_missing_message_returns_error(self):
        result = _tool_chat(MagicMock(), {})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_chat_delegates_to_api_call_with_unified_chat(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"reply": "hi"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        with patch("starlette.testclient.TestClient", return_value=mock_client):
            saved_whitelist = AIOPEN_STATE.get("whitelist", {})
            AIOPEN_STATE["whitelist"] = {"/api/ai/unified_chat": True}
            try:
                result = _tool_chat(MagicMock(), {"message": "hello"})
                assert result["success"] is True
                # Verify the path used
                call_args = mock_client.post.call_args
                assert call_args[0][0] == "/api/ai/unified_chat"
                payload = call_args.kwargs.get("json") or call_args[1].get("json")
                assert payload["message"] == "hello"
                assert payload["source"] == "aiopen"
            finally:
                AIOPEN_STATE["whitelist"] = saved_whitelist


# ── invoke_tool — gap branches ────────────────────────────────


class TestInvokeToolExt:
    @pytest.mark.asyncio
    async def test_ui_action_with_session_id_extracts_it(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
                mock_hub.dispatch = AsyncMock(return_value={"success": True})
                await invoke_tool(
                    "ui_click",
                    {"selector": "#btn", "session_id": "sess-123"},
                    MagicMock(),
                )
                # session_id should be passed separately, not in params
                call_args = mock_hub.dispatch.call_args
                # action is positional[0], params is positional[1]
                params = (
                    call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("params")
                )
                assert "session_id" not in params
                assert call_args.kwargs["session_id"] == "sess-123"
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_action_without_session_id_passes_none(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
                mock_hub.dispatch = AsyncMock(return_value={"success": True})
                await invoke_tool(
                    "ui_navigate",
                    {"path": "/products"},
                    MagicMock(),
                )
                call_kwargs = mock_hub.dispatch.call_args.kwargs
                assert call_kwargs["session_id"] is None
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_action_empty_session_id_passes_none(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
                mock_hub.dispatch = AsyncMock(return_value={"success": True})
                await invoke_tool(
                    "ui_type",
                    {"selector": "#inp", "text": "hello", "session_id": ""},
                    MagicMock(),
                )
                call_kwargs = mock_hub.dispatch.call_args.kwargs
                assert call_kwargs["session_id"] is None
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_action_passes_action_name(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
                mock_hub.dispatch = AsyncMock(return_value={"success": True})
                await invoke_tool("ui_scroll", {"delta_y": 100}, MagicMock())
                call_args = mock_hub.dispatch.call_args
                # First positional arg is the action name
                assert call_args[0][0] == "scroll"
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_action_passes_timeout(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
                mock_hub.dispatch = AsyncMock(return_value={"success": True})
                await invoke_tool("ui_snapshot", {}, MagicMock())
                call_kwargs = mock_hub.dispatch.call_args.kwargs
                assert call_kwargs["timeout"] == 10.0
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_sessions_includes_remote_control_flag(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            result = await invoke_tool("ui_sessions", {}, MagicMock())
            assert result["success"] is True
            assert result["remote_control_enabled"] is True
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_ui_sessions_remote_control_disabled_still_returns_sessions(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = False
        try:
            result = await invoke_tool("ui_sessions", {}, MagicMock())
            # ui_sessions is NOT gated by remote_control_enabled
            assert result["success"] is True
            assert result["remote_control_enabled"] is False
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    @pytest.mark.asyncio
    async def test_invoke_tool_whitespace_name_treated_as_unknown(self):
        result = await invoke_tool("  ", {}, MagicMock())
        assert result["success"] is False
        assert "UNKNOWN_TOOL" in result.get("code", "")

    @pytest.mark.asyncio
    async def test_invoke_tool_args_not_dict_treated_as_empty(self):
        # args is a list, not dict -> becomes {}
        result = await invoke_tool("api_catalog", ["not", "a", "dict"], MagicMock())
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_each_ui_action_routes_correctly(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            for tool_name, expected_action in [
                ("ui_snapshot", "snapshot"),
                ("ui_navigate", "navigate"),
                ("ui_click", "click"),
                ("ui_type", "type"),
                ("ui_scroll", "scroll"),
            ]:
                with patch("app.application.aiopen.service.aiopen_cursor_hub") as mock_hub:
                    mock_hub.dispatch = AsyncMock(return_value={"success": True})
                    await invoke_tool(tool_name, {}, MagicMock())
                    call_args = mock_hub.dispatch.call_args
                    assert call_args[0][0] == expected_action
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved


# ── openclaw_chat_proxy — gap branches ────────────────────────


class TestOpenclawChatProxyExt:
    def test_non_json_response_falls_back_to_raw(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json at all"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is True
            assert status == 200
            assert payload["data"]["raw"] == "not json at all"

    def test_empty_response_body_returns_empty_dict(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is True
            assert status == 200
            assert payload["data"] == {}

    def test_http_error_with_empty_body_uses_str_err(self):
        import urllib.error

        err = urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, None)
        err.read = MagicMock(return_value=b"")
        with patch("app.application.aiopen.service.urllib.request.urlopen", side_effect=err):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is False
            assert status == 502
            assert payload["status_code"] == 503
            # Empty body -> message falls back to str(err)
            assert "Service Unavailable" in payload["message"] or "503" in payload["message"]

    def test_runtime_error_returns_502(self):
        with patch(
            "app.application.aiopen.service.urllib.request.urlopen",
            side_effect=RuntimeError("runtime fail"),
        ):
            payload, status = openclaw_chat_proxy("hi")
            assert payload["success"] is False
            assert status == 502
            assert "runtime fail" in payload["message"]

    def test_target_url_construction(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            openclaw_chat_proxy("test message")
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            # Default openclaw_base is http://localhost:28789
            assert req.full_url == "http://localhost:28789/api/chat"
            assert req.method == "POST"

    def test_request_payload_contains_message(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            openclaw_chat_proxy("my custom message")
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            # req.data is the JSON-encoded payload
            import json as _json

            payload = _json.loads(req.data.decode("utf-8"))
            assert payload["message"] == "my custom message"

    def test_request_has_json_content_type(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"{}"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.aiopen.service.urllib.request.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            openclaw_chat_proxy("hi")
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            assert req.headers["Content-type"] == "application/json"


# ── aiopen_manifest — additional checks ───────────────────────


class TestAiopenManifestExt:
    def test_protocol_fields(self):
        m = aiopen_manifest()
        assert m["protocol"]["guide"] == "/api/aiopen/guide"
        assert m["protocol"]["mcp"] == "/api/aiopen/mcp"
        assert m["protocol"]["rest_invoke"] == "/api/aiopen/invoke"
        assert m["protocol"]["ws_screen"] == "/api/aiopen/ws"
        assert m["protocol"]["auth_header"] == "X-AIOPEN-Key"

    def test_tools_count_matches_definitions(self):
        m = aiopen_manifest()
        assert len(m["tools"]) == len(TOOL_DEFINITIONS)
        # Verify each tool has only the 3 expected keys
        for tool in m["tools"]:
            assert set(tool.keys()) == {"name", "description", "inputSchema"}

    def test_tool_names_present(self):
        m = aiopen_manifest()
        names = {t["name"] for t in m["tools"]}
        expected = {
            "api_catalog",
            "api_call",
            "chat",
            "ui_sessions",
            "ui_snapshot",
            "ui_navigate",
            "ui_click",
            "ui_type",
            "ui_scroll",
        }
        assert names == expected


# ── build_aiopen_guide — additional fields ────────────────────


class TestBuildAiopenGuideExt:
    def test_remote_control_enabled_reflected(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = True
        try:
            guide = build_aiopen_guide("http://x")
            assert guide["remote_control_enabled"] is True
            assert "已开启" in guide["markdown"]
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    def test_remote_control_disabled_reflected(self):
        saved = AIOPEN_STATE.get("remote_control_enabled")
        AIOPEN_STATE["remote_control_enabled"] = False
        try:
            guide = build_aiopen_guide("http://x")
            assert guide["remote_control_enabled"] is False
            assert "未开启" in guide["markdown"]
        finally:
            AIOPEN_STATE["remote_control_enabled"] = saved

    def test_screen_sessions_online_field(self):
        guide = build_aiopen_guide("http://x")
        assert "screen_sessions_online" in guide
        assert isinstance(guide["screen_sessions_online"], int)

    def test_instructions_for_ai_is_list(self):
        guide = build_aiopen_guide("http://x")
        assert isinstance(guide["instructions_for_ai"], list)
        assert len(guide["instructions_for_ai"]) > 0

    def test_endpoints_complete(self):
        guide = build_aiopen_guide("http://localhost:5100")
        eps = guide["endpoints"]
        assert eps["guide"] == "http://localhost:5100/api/aiopen/guide"
        assert eps["manifest"] == "http://localhost:5100/api/aiopen/manifest"
        assert eps["mcp"] == "http://localhost:5100/api/aiopen/mcp"
        assert eps["invoke"] == "http://localhost:5100/api/aiopen/invoke"
        assert eps["keys"] == "http://localhost:5100/api/aiopen/keys"

    def test_install_url_field(self):
        guide = build_aiopen_guide("http://localhost:5100")
        assert guide["install_url"] == "http://localhost:5100/api/aiopen/install"

    def test_auth_header_field(self):
        guide = build_aiopen_guide("http://x")
        assert guide["auth_header"] == "X-AIOPEN-Key"

    def test_cursor_deeplink_field(self):
        guide = build_aiopen_guide("http://x")
        assert guide["cursor_deeplink"].startswith("cursor://")

    def test_prompt_for_user_contains_guide_url(self):
        guide = build_aiopen_guide("http://localhost:5100")
        assert "http://localhost:5100/api/aiopen/guide" in guide["prompt_for_user"]

    def test_markdown_contains_all_tool_names(self):
        guide = build_aiopen_guide("http://x")
        md = guide["markdown"]
        for tool in TOOL_DEFINITIONS:
            assert tool["name"] in md

    def test_markdown_contains_mcp_protocol_info(self):
        guide = build_aiopen_guide("http://x")
        md = guide["markdown"]
        assert "MCP-Protocol-Version" in md
        assert "Mcp-Session-Id" in md
        assert "initialize" in md
        assert "tools/list" in md
        assert "tools/call" in md

    def test_markdown_contains_rest_example(self):
        guide = build_aiopen_guide("http://x")
        md = guide["markdown"]
        assert "curl" in md
        assert "X-AIOPEN-Key" in md

    def test_empty_base_url(self):
        guide = build_aiopen_guide("")
        assert guide["base_url"] == ""
        assert guide["endpoints"]["mcp"] == "/api/aiopen/mcp"

    def test_mcp_config_template_in_guide(self):
        guide = build_aiopen_guide("http://x")
        template = guide["mcp_config_template"]
        assert "mcpServers" in template
        assert MCP_SERVER_NAME in template["mcpServers"]
