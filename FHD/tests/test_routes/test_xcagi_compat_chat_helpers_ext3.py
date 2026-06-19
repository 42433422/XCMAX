"""Tests for app.fastapi_routes.xcagi_compat_chat_helpers — additional coverage (ext3).

Focus on REMAINING uncovered lines:
- _chat_request_subject with client.host fallback (no xff, with client)
- _xcagi_chat_http_exc with httpx.ConnectError and httpx.HTTPError branches
- _xcagi_compat_reply_payload with tool result success=True (no notice appended)
- _xcagi_compat_reply_payload with tool result errors list truncation (>5 errors)
- _xcagi_compat_reply_payload with notice already in text (skip append)
- _extract_excel_paths_from_message with various delimiters and edge cases
- _extract_excel_paths_from_context with tuple paths and non-string values
- _merge_runtime_context_with_message_paths with context paths only (no message paths)
- _ensure_vector_index_if_needed with non-dict JSON result
- _ensure_vector_index_if_needed with dict result but no error key
- _xcagi_guarded_planner_stream_events with various event types
- _xcagi_planner_stream_bytes with mode setting, db read auth, vector index
- _xcagi_planner_stream_bytes with planner_workflow_interrupt_reply
- _xcagi_planner_stream_bytes with empty merged reply
- _xcagi_planner_stream_bytes with thinking steps
- _xcagi_planner_stream_bytes with error event
- _xcagi_planner_stream_bytes with requires_token event
- _xcagi_planner_stream_bytes with RECOVERABLE_ERRORS exception
- _xcagi_planner_stream_bytes_async with sentinel and error
- XcagiCompatChatBatchBody validation
- _chat_read_token_required_payload structure
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.fastapi_routes import xcagi_compat_chat_helpers as ch


# ---------------------------------------------------------------------------
# _chat_request_subject — client.host fallback
# ---------------------------------------------------------------------------


class TestChatRequestSubjectAdditional:
    def test_no_xff_with_client_host(self):
        """Test that client.host is used when x-forwarded-for is missing."""
        request = Mock()
        request.headers = {"user-agent": "TestAgent"}
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        result = ch._chat_request_subject(request)
        parts = result.split("|")
        assert parts[0] == "10.0.0.1"

    def test_xff_with_multiple_ips(self):
        """Test that first IP is used from comma-separated xff."""
        request = Mock()
        request.headers = {
            "x-forwarded-for": "1.2.3.4, 5.6.7.8, 9.10.11.12",
            "user-agent": "TestAgent",
        }
        result = ch._chat_request_subject(request)
        parts = result.split("|")
        assert parts[0] == "1.2.3.4"

    def test_xff_with_whitespace(self):
        """Test that xff with surrounding whitespace is stripped."""
        request = Mock()
        request.headers = {
            "x-forwarded-for": "  1.2.3.4  ",
            "user-agent": "TestAgent",
        }
        result = ch._chat_request_subject(request)
        parts = result.split("|")
        assert parts[0] == "1.2.3.4"

    def test_no_xff_no_client_no_ua(self):
        """Test fallback to 'unknown' when no IP info available."""
        request = Mock()
        request.headers = {}
        request.client = None
        result = ch._chat_request_subject(request)
        assert result.startswith("unknown|")

    def test_client_host_empty_string(self):
        """Test that empty client.host falls back to 'unknown'."""
        request = Mock()
        request.headers = {"user-agent": "TestAgent"}
        request.client = MagicMock()
        request.client.host = ""
        result = ch._chat_request_subject(request)
        parts = result.split("|")
        assert parts[0] == "unknown"

    def test_client_host_none(self):
        """Test that None client.host falls back to 'unknown'."""
        request = Mock()
        request.headers = {"user-agent": "TestAgent"}
        request.client = MagicMock()
        request.client.host = None
        result = ch._chat_request_subject(request)
        parts = result.split("|")
        assert parts[0] == "unknown"


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc — httpx branches
# ---------------------------------------------------------------------------


class TestXcagiChatHttpExcAdditional:
    def test_httpx_connect_error(self):
        """Test httpx.ConnectError branch."""
        import httpx

        exc = httpx.ConnectError("connection refused")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503
        assert "修茈平台" in result.detail or "无法连接" in result.detail

    def test_httpx_connect_error_with_market_env(self, monkeypatch):
        """Test httpx.ConnectError with XCAGI_MARKET_BASE_URL env."""
        import httpx

        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://custom.market/")
        exc = httpx.ConnectError("connection refused")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503
        assert "custom.market" in result.detail

    def test_httpx_connect_error_with_modstore_env(self, monkeypatch):
        """Test httpx.ConnectError with MODSTORE_PLATFORM_URL env (fallback)."""
        import httpx

        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        monkeypatch.setenv("MODSTORE_PLATFORM_URL", "https://modstore.example.com")
        exc = httpx.ConnectError("connection refused")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503
        assert "modstore.example.com" in result.detail

    def test_httpx_http_error(self):
        """Test httpx.HTTPError branch (non-ConnectError)."""
        import httpx

        exc = httpx.HTTPError("generic http error")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502
        assert "修茈平台 LLM 请求失败" in result.detail

    def test_httpx_request_error(self):
        """Test httpx.RequestError (subclass of HTTPError)."""
        import httpx

        exc = httpx.RequestError("request failed")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_value_error_empty_message(self):
        """Test ValueError with empty message falls through to 500."""
        exc = ValueError("")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 500

    def test_value_error_whitespace_message(self):
        """Test ValueError with whitespace-only message falls through to 500."""
        exc = ValueError("   ")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# _xcagi_compat_reply_payload — additional branches
# ---------------------------------------------------------------------------


class TestXcagiCompatReplyPayloadAdditional:
    def test_dict_reply_empty_response_and_text(self):
        """Test dict reply with empty response and text."""
        result = ch._xcagi_compat_reply_payload({"response": "", "text": ""})
        assert result["response"] == ""
        assert result["data"]["response"] == ""

    def test_dict_reply_no_response_no_text(self):
        """Test dict reply with no response or text keys."""
        result = ch._xcagi_compat_reply_payload({"other": "data"})
        assert result["response"] == ""

    def test_string_reply_empty(self):
        """Test empty string reply."""
        result = ch._xcagi_compat_reply_payload("")
        assert result["response"] == ""
        assert result["success"] is True

    def test_string_reply_none(self):
        """Test None reply (converted to empty string)."""
        result = ch._xcagi_compat_reply_payload(None)
        assert result["response"] == ""

    def test_with_tool_result_success_true(self):
        """Test tool result with success=True (no notice appended)."""
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={"success": True, "tool_key": "tool_a"},
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("原始回复")
        # success=True → no notice appended
        assert "工具反馈" not in result["response"]
        assert result["response"] == "原始回复"

    def test_with_tool_result_no_error_no_success_false(self):
        """Test tool result with no error and success not False."""
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={"tool_key": "tool_a", "message": "ok"},
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("原始回复")
        # No error, success not False → no notice
        assert "工具反馈" not in result["response"]

    def test_with_tool_result_errors_truncated(self):
        """Test tool result with more than 5 errors (truncation)."""
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "errors": ["e1", "e2", "e3", "e4", "e5", "e6", "e7"],
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("reply")
        # errors_preview should contain first 5 errors
        assert "e1" in result["response"]
        assert "e5" in result["response"]

    def test_with_tool_result_errors_with_none_values(self):
        """Test tool result with None values in errors list."""
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "errors": [None, "e2", None, "e4"],
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("reply")
        # None values should be filtered out in join
        assert "e2" in result["response"]
        assert "e4" in result["response"]

    def test_notice_already_in_text_not_appended(self):
        """Test that notice is not appended if already in text."""
        import app.application.tools as tools_mod

        # The notice includes tool_key, err_code, and err_msg when present
        text_with_notice = (
            "原始回复\n\n---\n**工具反馈**（最近一次）\n"
            "- 工具：`tool_a`\n- 错误码：`ERR001`"
        )
        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "error": "ERR001",
                    "tool_key": "tool_a",
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload(text_with_notice)
        # Notice already in text → not appended again
        assert result["response"] == text_with_notice

    def test_with_tool_result_err_msg_only(self):
        """Test tool result with only err_msg (no err_code)."""
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "message": "失败原因",
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("原始回复")
        # success=False → notice appended with message
        assert "工具反馈" in result["response"]
        assert "失败原因" in result["response"]
        # No err_code → no 错误码 line
        assert "错误码" not in result["response"]

    def test_with_tool_result_tool_key_only(self):
        """Test tool result with only tool_key."""
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "tool_key": "my_tool",
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("原始回复")
        assert "工具反馈" in result["response"]
        assert "my_tool" in result["response"]

    def test_with_tool_result_errors_preview_from_tool_data(self):
        """Test tool result with errors_preview in tool_data."""
        import app.application.tools as tools_mod

        def fake_flatten(raw):
            return {"errors_preview": "preview text here"}

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "error": "ERR001",
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": fake_flatten}),
        ):
            result = ch._xcagi_compat_reply_payload("原始回复")
        assert "preview text here" in result["response"]

    def test_with_runtime_context_update_none(self):
        """Test that runtime_context_update=None doesn't add runtime_context key."""
        result = ch._xcagi_compat_reply_payload("reply", runtime_context_update=None)
        assert "runtime_context" not in result["data"]

    def test_with_runtime_context_update_empty_dict(self):
        """Test that runtime_context_update={} adds empty dict."""
        result = ch._xcagi_compat_reply_payload("reply", runtime_context_update={})
        assert result["data"]["runtime_context"] == {}

    def test_with_kitten_attachments_empty(self):
        """Test with empty kitten_attachments."""
        result = ch._xcagi_compat_reply_payload("reply", kitten_attachments={})
        # No additional keys added
        assert result["data"]["response"] == "reply"

    def test_with_kitten_attachments_all_none(self):
        """Test that None values in kitten_attachments are skipped."""
        result = ch._xcagi_compat_reply_payload(
            "reply",
            kitten_attachments={"a": None, "b": None},
        )
        assert "a" not in result["data"]
        assert "b" not in result["data"]


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_message — additional edge cases
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromMessageAdditional:
    def test_path_with_at_prefix(self):
        """Test path with @ prefix."""
        result = ch._extract_excel_paths_from_message("@path/to/file.xlsx end")
        assert len(result) == 1
        assert "file.xlsx" in result[0]

    def test_path_with_backticks(self):
        """Test path wrapped in backticks (with space after closing backtick)."""
        result = ch._extract_excel_paths_from_message("`path/to/file.xlsx` end")
        # The closing backtick breaks the lookahead, so no match
        # This tests the regex behavior with wrapping delimiters
        assert len(result) == 0

    def test_path_with_quotes(self):
        """Test path wrapped in quotes (closing quote breaks lookahead)."""
        result = ch._extract_excel_paths_from_message('"path/to/file.xlsx" end')
        assert len(result) == 0

    def test_path_with_brackets(self):
        """Test path wrapped in brackets (closing bracket breaks lookahead)."""
        result = ch._extract_excel_paths_from_message("[path/to/file.xlsx] end")
        assert len(result) == 0

    def test_path_with_parentheses(self):
        """Test path wrapped in parentheses (closing paren breaks lookahead)."""
        result = ch._extract_excel_paths_from_message("(path/to/file.xlsx) end")
        assert len(result) == 0

    def test_path_with_braces(self):
        """Test path wrapped in braces (closing brace breaks lookahead)."""
        result = ch._extract_excel_paths_from_message("{path/to/file.xlsx} end")
        assert len(result) == 0

    def test_path_with_angle_brackets(self):
        """Test path wrapped in angle brackets (excluded from char class)."""
        result = ch._extract_excel_paths_from_message("<path/to/file.xlsx> end")
        # Angle brackets are excluded from the char class, so no match
        assert len(result) == 0

    def test_path_with_trailing_delimiter_after_extension(self):
        """Test path where extension is followed by delimiter."""
        result = ch._extract_excel_paths_from_message("path/to/file.xlsx, end")
        assert len(result) == 1

    def test_path_at_end_of_string(self):
        """Test path at end of string."""
        result = ch._extract_excel_paths_from_message("see file.xlsx")
        assert len(result) == 1

    def test_path_followed_by_period(self):
        """Test path followed by period."""
        result = ch._extract_excel_paths_from_message("see file.xlsx. end")
        assert len(result) == 1

    def test_path_followed_by_comma(self):
        """Test path followed by comma."""
        result = ch._extract_excel_paths_from_message("see file.xlsx, end")
        assert len(result) == 1

    def test_path_followed_by_chinese_comma(self):
        """Test path followed by Chinese comma."""
        result = ch._extract_excel_paths_from_message("see file.xlsx， end")
        assert len(result) == 1

    def test_path_followed_by_exclamation(self):
        """Test path followed by exclamation mark."""
        result = ch._extract_excel_paths_from_message("see file.xlsx! end")
        assert len(result) == 1

    def test_path_followed_by_question(self):
        """Test path followed by question mark."""
        result = ch._extract_excel_paths_from_message("see file.xlsx? end")
        assert len(result) == 1

    def test_multiple_different_paths(self):
        """Test multiple different paths."""
        result = ch._extract_excel_paths_from_message(
            "files a.xlsx and b.xlsx and c.xls end"
        )
        assert len(result) == 3

    def test_path_with_mixed_separators(self):
        """Test path with mixed forward and backslashes."""
        result = ch._extract_excel_paths_from_message(r"path\to/file.xlsx end")
        assert len(result) == 1
        assert "/" in result[0]
        assert "\\" not in result[0]


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_context — additional branches
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromContextAdditional:
    def test_tuple_paths(self):
        """Test that tuple paths are handled."""
        ctx = {"excel_file_paths": ("/a.xlsx", "/b.xls")}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 2

    def test_empty_string_path_skipped(self):
        """Test that empty string paths are skipped."""
        ctx = {"excel_file_path": ""}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_none_path_skipped(self):
        """Test that None paths are skipped."""
        ctx = {"excel_file_path": None}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_excel_analysis_not_dict(self):
        """Test that non-dict excel_analysis is skipped."""
        ctx = {"excel_analysis": "not a dict"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_excel_analysis_preview_not_dict(self):
        """Test that non-dict preview_data is skipped."""
        ctx = {"excel_analysis": {"preview_data": "not a dict"}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_excel_analysis_file_path_none(self):
        """Test that None file_path in excel_analysis is skipped."""
        ctx = {"excel_analysis": {"file_path": None}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_excel_analysis_preview_file_path_none(self):
        """Test that None file_path in preview_data is skipped."""
        ctx = {"excel_analysis": {"preview_data": {"file_path": None}}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_excel_file_paths_not_list_or_tuple(self):
        """Test that non-list/tuple excel_file_paths is skipped."""
        ctx = {"excel_file_paths": "not a list"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_excel_file_path_not_string(self):
        """Test that non-string excel_file_path is converted and checked."""
        ctx = {"excel_file_path": 123}
        result = ch._extract_excel_paths_from_context(ctx)
        # str(123) = "123" → no .xlsx extension → skipped
        assert len(result) == 0

    def test_backslash_in_context_path_converted(self):
        """Test that backslashes in context paths are converted."""
        ctx = {"excel_file_path": r"C:\path\to\file.xlsx"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1
        assert "/" in result[0]
        assert "\\" not in result[0]


# ---------------------------------------------------------------------------
# _merge_runtime_context_with_message_paths — additional
# ---------------------------------------------------------------------------


class TestMergeRuntimeContextAdditional:
    def test_empty_context_with_paths(self):
        """Test empty context with message paths."""
        ctx, paths = ch._merge_runtime_context_with_message_paths({}, "file.xlsx end")
        assert len(paths) == 1
        assert ctx["excel_file_path"] == paths[0]
        assert ctx["excel_file_paths"] == paths

    def test_context_with_excel_file_paths_only(self):
        """Test context with excel_file_paths but no excel_file_path."""
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"excel_file_paths": ["/ctx/a.xlsx"]}, "no paths here"
        )
        # No message paths, but context has paths
        assert paths == []
        # all_paths should be populated from context
        assert "excel_file_paths" in ctx

    def test_context_with_excel_analysis(self):
        """Test context with excel_analysis dict."""
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"excel_analysis": {"file_path": "/analysis.xlsx"}}, "no paths here"
        )
        assert paths == []
        assert "excel_file_paths" in ctx

    def test_message_and_context_same_basename(self):
        """Test that message path with same basename as context path is deduplicated."""
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "/ctx/file.xlsx"}, "file.xlsx end"
        )
        # Same basename → should be deduplicated
        assert len(paths) == 1
        # Context path should be preferred (comes first in all_paths)
        assert ctx["excel_file_paths"][0] == "/ctx/file.xlsx"

    def test_none_context_with_none_message(self):
        """Test None context with None message."""
        ctx, paths = ch._merge_runtime_context_with_message_paths(None, None)
        assert paths == []
        assert ctx == {}

    def test_context_preserved(self):
        """Test that existing context keys are preserved."""
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"other_key": "value", "excel_file_path": "/ctx/file.xlsx"},
            "file.xlsx end",
        )
        assert ctx["other_key"] == "value"


# ---------------------------------------------------------------------------
# _ensure_vector_index_if_needed — additional
# ---------------------------------------------------------------------------


class TestEnsureVectorIndexIfNeededAdditional:
    def test_vector_request_with_empty_file_path(self):
        """Test vector request with empty file_path."""
        result = ch._ensure_vector_index_if_needed(
            "建立向量索引", {"excel_file_path": ""}
        )
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_with_none_file_path(self):
        """Test vector request with None file_path."""
        result = ch._ensure_vector_index_if_needed(
            "建立向量索引", {"excel_file_path": None}
        )
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_with_whitespace_file_path(self):
        """Test vector request with whitespace-only file_path."""
        result = ch._ensure_vector_index_if_needed(
            "建立向量索引", {"excel_file_path": "   "}
        )
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_no_excel_file_path_key(self):
        """Test vector request with no excel_file_path key."""
        result = ch._ensure_vector_index_if_needed("建立向量索引", {})
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_success_no_error(self):
        """Test vector request with success result (no error key)."""
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor"
        ) as mock_resolver:
            mock_executor = Mock(return_value='{"status": "ok", "rows": 100}')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is None

    def test_vector_request_with_non_dict_json(self):
        """Test vector request with non-dict JSON result."""
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor"
        ) as mock_resolver:
            mock_executor = Mock(return_value='["not", "a", "dict"]')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        # Non-dict result → no error → returns None
        assert result is None

    def test_vector_request_with_error_no_message(self):
        """Test vector request with error but no message."""
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor"
        ) as mock_resolver:
            mock_executor = Mock(return_value='{"error": "failed"}')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is not None
        assert "failed" in result

    def test_vector_request_with_json_decode_error(self):
        """Test vector request with JSON decode error."""
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor"
        ) as mock_resolver:
            mock_executor = Mock(return_value="not valid json")
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        # JSON decode error is RECOVERABLE_ERROR → returns error message
        assert result is not None
        assert "/test.xlsx" in result

    def test_vector_request_with_import_error(self):
        """Test vector request with ImportError."""
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            side_effect=ImportError("module not found"),
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers.RECOVERABLE_ERRORS",
            (RuntimeError, ImportError, ValueError),
        ):
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is not None
        assert "module not found" in result


# ---------------------------------------------------------------------------
# _xcagi_planner_stream_bytes — additional branches
# ---------------------------------------------------------------------------


class TestXcagiPlannerStreamBytesAdditional:
    def _make_request(self):
        request = Mock()
        request.headers = {}
        request.client = None
        return request

    def _make_body(self, message="hello", mode=None, db_read_token=None):
        return ch.XcagiCompatChatBody(
            message=message, mode=mode, db_read_token=db_read_token
        )

    def test_mode_online_sets_llm_mode(self):
        """Test that mode='online' calls set_llm_mode."""
        request = self._make_request()
        body = self._make_body(mode="online")
        with (
            patch("app.fastapi_routes.xcagi_compat_chat_helpers.set_llm_mode") as mock_set,
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter([{"type": "token", "text": "hello"}]),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))
        mock_set.assert_called_once_with("online")

    def test_mode_offline_sets_llm_mode(self):
        """Test that mode='offline' calls set_llm_mode."""
        request = self._make_request()
        body = self._make_body(mode="OFFLINE")
        with (
            patch("app.fastapi_routes.xcagi_compat_chat_helpers.set_llm_mode") as mock_set,
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter([{"type": "token", "text": "hello"}]),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))
        mock_set.assert_called_once_with("offline")

    def test_mode_other_does_not_set_llm_mode(self):
        """Test that other mode values don't call set_llm_mode."""
        request = self._make_request()
        body = self._make_body(mode="custom")
        with (
            patch("app.fastapi_routes.xcagi_compat_chat_helpers.set_llm_mode") as mock_set,
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter([{"type": "token", "text": "hello"}]),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))
        mock_set.assert_not_called()

    def test_db_read_not_authorized_yields_token_and_requires_token(self):
        """Test that unauthorized db read yields token and requires_token events."""
        request = self._make_request()
        body = self._make_body(message="查询数据库", db_read_token="wrong")
        read_req = {
            "requires_token": True,
            "token_name": "DB_READ_TOKEN",
            "token_description": "数据库查看令牌",
            "message": "需要令牌",
        }
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(False, read_req),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield 2 events: token and requires_token
        assert len(results) == 2
        # First event: token with authorization message
        first_data = json.loads(results[0].replace(b"data: ", b"").strip())
        assert first_data["type"] == "token"
        assert "数据库查看令牌" in first_data["text"]
        # Second event: requires_token
        second_data = json.loads(results[1].replace(b"data: ", b"").strip())
        assert second_data["type"] == "requires_token"
        assert second_data["token_name"] == "DB_READ_TOKEN"

    def test_planner_workflow_interrupt_reply_returns_value(self):
        """Test that planner_workflow_interrupt_reply returning a value yields done."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value="interrupt reply",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_after_workflow_interrupt",
                return_value={"cleared": True},
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield 2 events: token and done
        assert len(results) == 2
        first_data = json.loads(results[0].replace(b"data: ", b"").strip())
        assert first_data["type"] == "token"
        assert first_data["text"] == "interrupt reply"
        second_data = json.loads(results[1].replace(b"data: ", b"").strip())
        assert second_data["type"] == "done"
        assert second_data["result"]["success"] is True

    def test_vector_error_yields_error_event(self):
        """Test that vector error yields error event."""
        request = self._make_request()
        body = self._make_body(message="建立向量索引")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value="vector index error",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        assert len(results) == 1
        data = json.loads(results[0].replace(b"data: ", b"").strip())
        assert data["type"] == "error"
        assert data["message"] == "vector index error"

    def test_empty_merged_reply_yields_error(self):
        """Test that empty merged reply yields error event."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter([{"type": "token", "text": ""}]),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield token event + error event
        assert len(results) == 2
        # Last event should be error
        last_data = json.loads(results[-1].replace(b"data: ", b"").strip())
        assert last_data["type"] == "error"
        assert "修茈平台未返回内容" in last_data["message"]

    def test_merged_reply_with_thinking_steps(self):
        """Test that merged reply with thinking steps yields done with dict reply."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter(
                    [
                        {"type": "token", "text": "[正在调用工具:查询]"},
                        {"type": "token", "text": "result"},
                    ]
                ),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield 2 token events + 1 done event
        assert len(results) == 3
        last_data = json.loads(results[-1].replace(b"data: ", b"").strip())
        assert last_data["type"] == "done"
        assert last_data["result"]["success"] is True
        # thinking_steps should be present
        assert last_data["result"]["data"]["thinking_steps"] is not None

    def test_error_event_in_stream(self):
        """Test that error event in stream is yielded and returns."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter(
                    [
                        {"type": "token", "text": "partial"},
                        {"type": "error", "message": "stream error"},
                    ]
                ),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield token + error, then return
        assert len(results) == 2
        last_data = json.loads(results[-1].replace(b"data: ", b"").strip())
        assert last_data["type"] == "error"
        assert last_data["message"] == "stream error"

    def test_requires_token_event_halts_stream(self):
        """Test that requires_token event halts the stream."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter(
                    [
                        {"type": "token", "text": "partial"},
                        {"type": "requires_token", "token_name": "WRITE_TOKEN"},
                    ]
                ),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield token + requires_token, then return (no done event)
        assert len(results) == 2
        last_data = json.loads(results[-1].replace(b"data: ", b"").strip())
        assert last_data["type"] == "requires_token"

    def test_done_event_in_stream_continues(self):
        """Test that done event in stream continues (doesn't return)."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter(
                    [
                        {"type": "done"},
                        {"type": "token", "text": "after done"},
                    ]
                ),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # done event is skipped (continue), then token + final done
        assert len(results) >= 2

    def test_unknown_event_type_yielded(self):
        """Test that unknown event types are yielded."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter(
                    [
                        {"type": "custom", "data": "value"},
                        {"type": "token", "text": "result"},
                    ]
                ),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield custom + token + done
        assert len(results) >= 2

    def test_recoverable_error_exception(self):
        """Test that RECOVERABLE_ERRORS exception yields error event."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                side_effect=RuntimeError("stream failed"),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield error event
        assert len(results) == 1
        data = json.loads(results[0].replace(b"data: ", b"").strip())
        assert data["type"] == "error"

    def test_ephemeral_token_not_added_to_reply_parts(self):
        """Test that ephemeral tokens are not added to reply_parts."""
        request = self._make_request()
        body = self._make_body(message="hello")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter(
                    [
                        {"type": "token", "text": "ephemeral", "ephemeral": True},
                        {"type": "token", "text": "real"},
                    ]
                ),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ),
        ):
            results = list(
                ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard")
            )
        # Should yield 2 tokens + done
        assert len(results) == 3
        last_data = json.loads(results[-1].replace(b"data: ", b"").strip())
        assert last_data["type"] == "done"
        # reply should only contain "real", not "ephemeral"
        assert last_data["result"]["response"] == "real"

    def test_db_read_authorized_with_db_read_message_sets_context(self):
        """Test that db read authorized with db read message sets chat_db_read_authorized."""
        request = self._make_request()
        body = self._make_body(message="查询数据库", db_read_token="valid")
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_chat_db_read_authorized",
                return_value=(True, None),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.planner_workflow_interrupt_reply",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._ensure_vector_index_if_needed",
                return_value=None,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.create_modstore_openai_client_from_request",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_guarded_planner_stream_events",
                return_value=iter([{"type": "token", "text": "result"}]),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.runtime_context_with_tier",
                side_effect=lambda ctx, tier: ctx,
            ) as mock_tier,
        ):
            list(ch._xcagi_planner_stream_bytes(request, body, ai_tier="standard"))
        # runtime_context_with_tier should be called with context that has chat_db_read_authorized
        call_args = mock_tier.call_args
        ctx = call_args[0][0]
        assert ctx.get("chat_db_read_authorized") is True


# ---------------------------------------------------------------------------
# _xcagi_planner_stream_bytes_async — additional
# ---------------------------------------------------------------------------


class TestXcagiPlannerStreamBytesAsyncAdditional:
    @pytest.mark.asyncio
    async def test_async_wrapper_yields_chunks(self):
        """Test that async wrapper yields chunks from sync generator."""
        request = Mock()
        request.headers = {}
        request.client = None
        body = ch.XcagiCompatChatBody(message="hello")

        def mock_sync_gen(*args, **kwargs):
            yield b"chunk1"
            yield b"chunk2"

        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_planner_stream_bytes",
            side_effect=mock_sync_gen,
        ):
            results = []
            async for chunk in ch._xcagi_planner_stream_bytes_async(
                request, body, ai_tier="standard"
            ):
                results.append(chunk)
        assert results == [b"chunk1", b"chunk2"]

    @pytest.mark.asyncio
    async def test_async_wrapper_with_exception(self):
        """Test that async wrapper handles exception from sync generator."""
        request = Mock()
        request.headers = {}
        request.client = None
        body = ch.XcagiCompatChatBody(message="hello")

        def mock_sync_gen(*args, **kwargs):
            yield b"chunk1"
            raise RuntimeError("async error")

        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_planner_stream_bytes",
            side_effect=mock_sync_gen,
        ):
            results = []
            async for chunk in ch._xcagi_planner_stream_bytes_async(
                request, body, ai_tier="standard"
            ):
                results.append(chunk)
        # Should yield chunk1 + error event
        assert b"chunk1" in results
        # Last item should be error event
        assert any(b"error" in r for r in results)

    @pytest.mark.asyncio
    async def test_async_wrapper_empty_generator(self):
        """Test that async wrapper handles empty generator."""
        request = Mock()
        request.headers = {}
        request.client = None
        body = ch.XcagiCompatChatBody(message="hello")

        def mock_sync_gen(*args, **kwargs):
            return
            yield  # never reached

        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_planner_stream_bytes",
            side_effect=mock_sync_gen,
        ):
            results = []
            async for chunk in ch._xcagi_planner_stream_bytes_async(
                request, body, ai_tier="standard"
            ):
                results.append(chunk)
        assert results == []


# ---------------------------------------------------------------------------
# _xcagi_guarded_planner_stream_events — additional
# ---------------------------------------------------------------------------


class TestXcagiGuardedPlannerStreamEventsAdditional:
    def test_normal_events_yielded(self):
        """Test that normal events are yielded."""
        body = ch.XcagiCompatChatBody(message="hello")

        def mock_chat_stream(*args, **kwargs):
            yield {"type": "token", "text": "hello"}
            yield {"type": "token", "text": " world"}

        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers.chat_stream_sse_events",
            side_effect=mock_chat_stream,
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_chat_timeout_seconds",
            return_value=600.0,
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_stream_first_token_timeout_seconds",
            return_value=120.0,
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_stream_idle_notice_seconds",
            return_value=60.0,
        ):
            results = list(
                ch._xcagi_guarded_planner_stream_events(
                    body,
                    runtime_context={},
                    workspace_root="/tmp",
                    client=Mock(),
                )
            )
        assert len(results) == 2
        assert results[0]["text"] == "hello"
        assert results[1]["text"] == " world"

    def test_exception_in_worker_yields_error(self):
        """Test that exception in worker yields error event."""
        body = ch.XcagiCompatChatBody(message="hello")

        def mock_chat_stream(*args, **kwargs):
            raise RuntimeError("worker failed")
            yield  # never reached

        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers.chat_stream_sse_events",
            side_effect=mock_chat_stream,
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_chat_timeout_seconds",
            return_value=600.0,
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_stream_first_token_timeout_seconds",
            return_value=120.0,
        ), patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._xcagi_stream_idle_notice_seconds",
            return_value=60.0,
        ):
            results = list(
                ch._xcagi_guarded_planner_stream_events(
                    body,
                    runtime_context={},
                    workspace_root="/tmp",
                    client=Mock(),
                )
            )
        # Should yield error event
        assert len(results) == 1
        assert results[0]["type"] == "error"


# ---------------------------------------------------------------------------
# XcagiCompatChatBatchBody — additional validation
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBatchBodyAdditional:
    def test_default_values(self):
        body = ch.XcagiCompatChatBatchBody()
        assert body.messages == []
        assert body.context is None
        assert body.system_prompt is None
        assert body.mode is None
        assert body.db_read_token is None
        assert body.db_write_token is None
        assert body.user_id is None
        assert body.source is None

    def test_with_messages(self):
        body = ch.XcagiCompatChatBatchBody(messages=["msg1", "msg2"])
        assert body.messages == ["msg1", "msg2"]

    def test_with_context_alias(self):
        body = ch.XcagiCompatChatBatchBody(runtime_context={"k": "v"})
        assert body.context == {"k": "v"}

    def test_with_system_prompt_alias(self):
        body = ch.XcagiCompatChatBatchBody(instructions="sys")
        assert body.system_prompt == "sys"

    def test_with_mode_alias(self):
        body = ch.XcagiCompatChatBatchBody(llm_mode="online")
        assert body.mode == "online"

    def test_with_user_id_and_source(self):
        body = ch.XcagiCompatChatBatchBody(user_id="u123", source="mobile")
        assert body.user_id == "u123"
        assert body.source == "mobile"

    def test_extra_fields_ignored(self):
        body = ch.XcagiCompatChatBatchBody(messages=["msg"], extra_field="ignored")
        assert not hasattr(body, "extra_field")


# ---------------------------------------------------------------------------
# _chat_read_token_required_payload — structure
# ---------------------------------------------------------------------------


class TestChatReadTokenRequiredPayload:
    def test_payload_structure(self):
        result = ch._chat_read_token_required_payload("some message")
        assert result["requires_token"] is True
        assert result["token_name"] == "DB_READ_TOKEN"
        assert "token_description" in result
        assert "message" in result
        assert "5 分钟" in result["token_description"]

    def test_payload_ignores_message(self):
        """Test that the message parameter is ignored (prefixed with _)."""
        result1 = ch._chat_read_token_required_payload("message1")
        result2 = ch._chat_read_token_required_payload("message2")
        assert result1 == result2


# ---------------------------------------------------------------------------
# _message_requires_db_read_token — additional patterns
# ---------------------------------------------------------------------------


class TestMessageRequiresDbReadTokenAdditional:
    def test_browse_database(self):
        assert ch._message_requires_db_read_token("浏览数据库") is True

    def test_read_data_table(self):
        assert ch._message_requires_db_read_token("读取数据表") is True

    def test_view_customer_library(self):
        assert ch._message_requires_db_read_token("查看客户库") is True

    def test_product_library_query(self):
        assert ch._message_requires_db_read_token("产品库查询") is True

    def test_whitespace_message(self):
        assert ch._message_requires_db_read_token("   ") is False

    def test_message_with_only_db_keyword(self):
        """Test message with only '数据库' but no action verb."""
        assert ch._message_requires_db_read_token("数据库") is False

    def test_message_with_only_action_verb(self):
        """Test message with only '查看' but no db keyword."""
        assert ch._message_requires_db_read_token("查看") is False


# ---------------------------------------------------------------------------
# _chat_db_read_grace_seconds_left — additional
# ---------------------------------------------------------------------------


class TestChatDbReadGraceSecondsLeftAdditional:
    def test_grace_exactly_now(self):
        """Test that grace exactly at now returns 0."""
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        now = time.time()
        key = ch._chat_request_subject(request)
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_until",
            {key: now},
        ):
            result = ch._chat_db_read_grace_seconds_left(request)
        assert result == 0

    def test_grace_just_expired(self):
        """Test that grace just expired returns 0 and cleans up."""
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        past_time = time.time() - 1
        key = ch._chat_request_subject(request)
        grace_dict = {key: past_time}
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_until",
            grace_dict,
        ):
            result = ch._chat_db_read_grace_seconds_left(request)
        assert result == 0


# ---------------------------------------------------------------------------
# _touch_chat_db_read_grace — additional
# ---------------------------------------------------------------------------


class TestTouchChatDbReadGraceAdditional:
    def test_touch_sets_grace_for_subject(self):
        """Test that touch sets grace for the request subject."""
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        key = ch._chat_request_subject(request)
        # Clear any existing grace
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_until",
            {},
        ) as grace_dict:
            result = ch._touch_chat_db_read_grace(request)
        assert result == ch._CHAT_DB_READ_GRACE_SEC


# ---------------------------------------------------------------------------
# _thinking_steps_from_planner_stream_text — additional
# ---------------------------------------------------------------------------


class TestThinkingStepsFromPlannerStreamTextAdditional:
    def test_whitespace_only_text(self):
        """Test that whitespace-only text returns None."""
        assert ch._thinking_steps_from_planner_stream_text("   ") is None

    def test_mixed_markers(self):
        """Test text with mixed marker types."""
        text = "[正在调用工具:查询] some text [工具已返回结果] more [需要授权:TOKEN]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "[正在调用工具:查询]" in result
        assert "[工具已返回结果]" in result
        assert "[需要授权:TOKEN]" in result

    def test_tool_returned_with_details(self):
        """Test [工具已返回...] with details."""
        text = "[工具已返回 3 行数据]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "[工具已返回 3 行数据]" in result

    def test_tool_failed_with_details(self):
        """Test [工具未成功...] with details."""
        text = "[工具未成功: 超时]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "[工具未成功: 超时]" in result

    def test_multiple_same_markers_deduplicated(self):
        """Test that multiple identical markers are deduplicated."""
        text = "[正在调用工具:a][正在调用工具:a][正在调用工具:a]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_error_payload — additional
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutErrorPayloadAdditional:
    def test_with_zero_timeout(self):
        """Test payload with zero timeout."""
        result = ch._xcagi_chat_timeout_error_payload(0.0)
        assert result["success"] is False
        assert "0" in result["message"]

    def test_with_large_timeout(self):
        """Test payload with large timeout."""
        result = ch._xcagi_chat_timeout_error_payload(600.0)
        assert result["success"] is False
        assert "600" in result["message"]

    def test_data_structure(self):
        """Test that data structure is correct."""
        result = ch._xcagi_chat_timeout_error_payload(120.0)
        assert "data" in result
        assert "text" in result["data"]
        assert "response" in result["data"]
        assert result["data"]["text"] == result["data"]["response"]
        assert result["data"]["text"] == result["message"]
