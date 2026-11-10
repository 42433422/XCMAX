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
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.fastapi_routes import xcagi_compat_chat_helpers as ch


def _patch_chat(name, *args, **kwargs):
    """Keep patches on the compatibility facade, not its implementation module."""
    return patch(f"app.fastapi_routes.xcagi_compat_chat_helpers.{name}", *args, **kwargs)


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
        result = ch._extract_excel_paths_from_message("files a.xlsx and b.xlsx and c.xls end")
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
        result = ch._ensure_vector_index_if_needed("建立向量索引", {"excel_file_path": ""})
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_with_none_file_path(self):
        """Test vector request with None file_path."""
        result = ch._ensure_vector_index_if_needed("建立向量索引", {"excel_file_path": None})
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_with_whitespace_file_path(self):
        """Test vector request with whitespace-only file_path."""
        result = ch._ensure_vector_index_if_needed("建立向量索引", {"excel_file_path": "   "})
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_no_excel_file_path_key(self):
        """Test vector request with no excel_file_path key."""
        result = ch._ensure_vector_index_if_needed("建立向量索引", {})
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_success_no_error(self):
        """Test vector request with success result (no error key)."""
        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolver:
            mock_executor = Mock(return_value='{"status": "ok", "rows": 100}')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is None

    def test_vector_request_with_non_dict_json(self):
        """Test vector request with non-dict JSON result."""
        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolver:
            mock_executor = Mock(return_value='["not", "a", "dict"]')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        # Non-dict result → no error → returns None
        assert result is None

    def test_vector_request_with_error_no_message(self):
        """Test vector request with error but no message."""
        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolver:
            mock_executor = Mock(return_value='{"error": "failed"}')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is not None
        assert "failed" in result

    def test_vector_request_with_json_decode_error(self):
        """Test vector request with JSON decode error."""
        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolver:
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
        with (
            patch(
                "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
                side_effect=ImportError("module not found"),
            ),
            _patch_chat(
                "RECOVERABLE_ERRORS",
                (RuntimeError, ImportError, ValueError),
            ),
        ):
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is not None
        assert "module not found" in result


# ---------------------------------------------------------------------------
# _xcagi_planner_stream_bytes_async — additional
# ---------------------------------------------------------------------------


class TestXcagiPlannerStreamBytesAsyncAdditional:
    @pytest.mark.asyncio
    async def test_async_wrapper_yields_chunks(self):
        request = Mock()
        request.headers = {}
        request.client = None
        body = ch.XcagiCompatChatBody(message="hello")

        def mock_sync_gen(*args, **kwargs):
            yield b"chunk1"
            yield b"chunk2"

        with _patch_chat(
            "_xcagi_planner_stream_bytes",
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

        with _patch_chat(
            "_xcagi_planner_stream_bytes",
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

        with _patch_chat(
            "_xcagi_planner_stream_bytes",
            side_effect=mock_sync_gen,
        ):
            results = []
            async for chunk in ch._xcagi_planner_stream_bytes_async(
                request, body, ai_tier="standard"
            ):
                results.append(chunk)
        assert results == []


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
        assert ch._message_requires_db_read_token("查看客户库") is False

    def test_product_library_query(self):
        assert ch._message_requires_db_read_token("产品库查询") is False

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
        with _patch_chat(
            "_chat_db_read_grace_until",
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
        with _patch_chat(
            "_chat_db_read_grace_until",
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
        with _patch_chat(
            "_chat_db_read_grace_until",
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
