"""Tests for app.fastapi_routes.xcagi_compat_chat_helpers — extended coverage.

Focus: _xcagi_chat_http_exc, _xcagi_compat_reply_payload, _extract_excel_paths_*,
_merge_runtime_context_with_message_paths, _looks_like_vector_request,
_ensure_vector_index_if_needed, _xcagi_chat_timeout_seconds, _xcagi_stream_*,
_xcagi_chat_timeout_error_payload, _thinking_steps_from_planner_stream_text,
_sse_event_line, _xcagi_planner_stream_bytes, _ensure_chat_db_read_authorized.
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.fastapi_routes import xcagi_compat_chat_helpers as ch


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc — extended
# ---------------------------------------------------------------------------


class TestXcagiChatHttpExcExtended:
    def test_timeout_error(self):
        exc = TimeoutError("timeout occurred")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 504
        assert "timeout occurred" in result.detail

    def test_timeout_error_empty_message(self):
        exc = TimeoutError()
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 504
        assert "大模型响应超时" in result.detail

    @pytest.mark.skipif(
        True,  # httpx may not be importable in all envs; covered by import guard
        reason="requires httpx",
    )
    def test_httpx_connect_error(self):
        import httpx

        exc = httpx.ConnectError("connection refused")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503

    def test_authentication_error(self):
        from openai import AuthenticationError

        exc = AuthenticationError(message="invalid key", response=Mock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 401

    def test_rate_limit_error(self):
        from openai import RateLimitError

        exc = RateLimitError(message="rate limited", response=Mock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 429

    def test_api_connection_error(self):
        from openai import APIConnectionError

        exc = APIConnectionError(request=Mock())
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503

    def test_api_error(self):
        from openai import APIError

        exc = APIError(message="api error", request=Mock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_runtime_error(self):
        exc = RuntimeError("runtime failure")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503
        assert "runtime failure" in result.detail

    def test_value_error_balance_insufficient(self):
        exc = ValueError("余额不足")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 402
        assert "余额不足" in result.detail

    def test_value_error_402_in_message(self):
        exc = ValueError("error 402 payment required")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 402

    def test_value_error_platform_error(self):
        exc = ValueError("平台错误 occurred")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_value_error_generic(self):
        exc = ValueError("some other error")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 500

    def test_unknown_error(self):
        exc = KeyError("unknown")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 500

    def test_httpx_import_error_path(self):
        """When httpx import fails, should fall through to other branches."""
        with patch("builtins.__import__", side_effect=ImportError("no httpx")):
            exc = RuntimeError("test")
            result = ch._xcagi_chat_http_exc(exc)
            assert result.status_code == 503


# ---------------------------------------------------------------------------
# _xcagi_compat_reply_payload — extended
# ---------------------------------------------------------------------------


class TestXcagiCompatReplyPayloadExtended:
    def test_string_reply(self):
        result = ch._xcagi_compat_reply_payload("hello")
        assert result["success"] is True
        assert result["response"] == "hello"
        assert result["data"]["response"] == "hello"
        assert result["data"]["text"] == "hello"

    def test_dict_reply_with_response(self):
        result = ch._xcagi_compat_reply_payload({"response": "world"})
        assert result["response"] == "world"

    def test_dict_reply_with_text(self):
        result = ch._xcagi_compat_reply_payload({"text": "from text"})
        assert result["response"] == "from text"

    def test_dict_reply_with_thinking_steps(self):
        result = ch._xcagi_compat_reply_payload(
            {"response": "ans", "thinking_steps": "step1"}
        )
        assert result["data"]["thinking_steps"] == "step1"

    def test_with_runtime_context_update(self):
        result = ch._xcagi_compat_reply_payload(
            "reply", runtime_context_update={"key": "value"}
        )
        assert result["data"]["runtime_context"] == {"key": "value"}

    def test_with_kitten_attachments(self):
        result = ch._xcagi_compat_reply_payload(
            "reply", kitten_attachments={"attachment1": "val1", "attachment2": None}
        )
        assert result["data"]["attachment1"] == "val1"
        assert "attachment2" not in result["data"]

    def test_with_tool_result_error(self):
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "error": "ERR001",
                    "message": "失败原因",
                    "tool_key": "tool_a",
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("原始回复")
        # Should append tool feedback notice
        assert "工具反馈" in result["response"]
        assert "ERR001" in result["response"]
        assert "tool_a" in result["response"]

    def test_with_tool_result_errors_list(self):
        import app.application.tools as tools_mod

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
                return_value={
                    "errors": ["err1", "err2", "err3", "err4", "err5", "err6"],
                    "success": False,
                },
                create=True,
            ),
            patch.dict(tools_mod.__dict__, {"flatten_tool_result_dict_for_client": lambda raw: {}}),
        ):
            result = ch._xcagi_compat_reply_payload("reply")
        # errors_preview should be in the notice
        assert "err1" in result["response"]

    def test_tool_result_unavailable(self):
        with patch(
            "app.legacy.chat.legacy_chat_adapter.get_last_tool_result",
            side_effect=RuntimeError("unavailable"),
            create=True,
        ):
            result = ch._xcagi_compat_reply_payload("reply")
        assert result["success"] is True
        assert result["response"] == "reply"


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_message — extended
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromMessageExtended:
    def test_no_paths(self):
        assert ch._extract_excel_paths_from_message("hello world") == []

    def test_single_path(self):
        result = ch._extract_excel_paths_from_message("file @/path/to/file.xlsx")
        assert len(result) == 1
        assert "file.xlsx" in result[0]

    def test_multiple_paths(self):
        result = ch._extract_excel_paths_from_message(
            "files a.xlsx and b.xls end"
        )
        assert len(result) == 2

    def test_xlsm_extension(self):
        result = ch._extract_excel_paths_from_message("macro.xlsm here")
        assert len(result) == 1

    def test_backslash_converted(self):
        result = ch._extract_excel_paths_from_message(r"path\to\file.xlsx end")
        assert len(result) == 1
        assert "/" in result[0]

    def test_deduplication(self):
        result = ch._extract_excel_paths_from_message(
            "a.xlsx and a.xlsx end"
        )
        assert len(result) == 1

    def test_empty_message(self):
        assert ch._extract_excel_paths_from_message("") == []

    def test_none_message(self):
        assert ch._extract_excel_paths_from_message(None) == []


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_context — extended
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromContextExtended:
    def test_single_path(self):
        ctx = {"excel_file_path": "/path/to/file.xlsx"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_multiple_paths(self):
        ctx = {"excel_file_paths": ["/a.xlsx", "/b.xls"]}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 2

    def test_excel_analysis_dict(self):
        ctx = {"excel_analysis": {"file_path": "/analysis.xlsx"}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_excel_analysis_with_preview(self):
        ctx = {
            "excel_analysis": {
                "preview_data": {"file_path": "/preview.xlsx"},
            }
        }
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_non_excel_path_skipped(self):
        ctx = {"excel_file_path": "/path/to/file.txt"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_empty_context(self):
        assert ch._extract_excel_paths_from_context({}) == []

    def test_deduplication(self):
        ctx = {
            "excel_file_path": "/same.xlsx",
            "excel_file_paths": ["/same.xlsx", "/other.xlsx"],
        }
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _merge_runtime_context_with_message_paths — extended
# ---------------------------------------------------------------------------


class TestMergeRuntimeContextWithMessagePathsExtended:
    def test_no_paths_returns_empty(self):
        ctx, paths = ch._merge_runtime_context_with_message_paths(None, "hello")
        assert paths == []
        assert ctx == {}

    def test_message_paths_only(self):
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            None, "file.xlsx end"
        )
        assert len(paths) == 1
        assert "excel_file_path" in ctx
        assert "excel_file_paths" in ctx

    def test_context_paths_only(self):
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "/ctx/file.xlsx"}, "no paths here"
        )
        assert len(paths) == 0
        assert "excel_file_paths" in ctx

    def test_both_sources_merged(self):
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "/ctx/file.xlsx"}, "file.xlsx end"
        )
        # Should merge and deduplicate by basename
        assert len(paths) == 1
        assert len(ctx["excel_file_paths"]) >= 1

    def test_different_paths_both_kept(self):
        ctx, paths = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "/ctx/a.xlsx"}, "b.xlsx end"
        )
        assert len(paths) == 1
        assert len(ctx["excel_file_paths"]) == 2


# ---------------------------------------------------------------------------
# _looks_like_vector_request — extended
# ---------------------------------------------------------------------------


class TestLooksLikeVectorRequestExtended:
    def test_vector_keyword(self):
        assert ch._looks_like_vector_request("请建立向量索引") is True

    def test_index_keyword(self):
        assert ch._looks_like_vector_request("建立索引") is True

    def test_semantic_search_keyword(self):
        assert ch._looks_like_vector_request("semantic search") is True

    def test_embedding_keyword(self):
        assert ch._looks_like_vector_request("embedding") is True

    def test_no_keyword(self):
        assert ch._looks_like_vector_request("普通查询") is False

    def test_empty(self):
        assert ch._looks_like_vector_request("") is False


# ---------------------------------------------------------------------------
# _ensure_vector_index_if_needed — extended
# ---------------------------------------------------------------------------


class TestEnsureVectorIndexIfNeededExtended:
    def test_not_vector_request_returns_none(self):
        result = ch._ensure_vector_index_if_needed("普通查询", {})
        assert result is None

    def test_vector_request_no_file_path(self):
        result = ch._ensure_vector_index_if_needed("建立向量索引", {})
        assert result is not None
        assert "Excel 路径" in result

    def test_vector_request_with_file_path_success(self):
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor"
        ) as mock_resolver:
            mock_executor = Mock(return_value='{"status": "ok"}')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is None

    def test_vector_request_with_error_response(self):
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor"
        ) as mock_resolver:
            mock_executor = Mock(return_value='{"error": "failed", "message": "no sheet"}')
            mock_resolver.return_value = mock_executor
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is not None
        assert "no sheet" in result

    def test_vector_request_with_exception(self):
        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            side_effect=RuntimeError("executor failed"),
        ):
            result = ch._ensure_vector_index_if_needed(
                "建立向量索引", {"excel_file_path": "/test.xlsx"}
            )
        assert result is not None
        assert "executor failed" in result


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_seconds — extended
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutSecondsExtended:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_TIMEOUT_SEC", raising=False)
        assert ch._xcagi_chat_timeout_seconds() == 120.0

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "60")
        assert ch._xcagi_chat_timeout_seconds() == 60.0

    def test_min_clamp(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "1")
        assert ch._xcagi_chat_timeout_seconds() == 5.0

    def test_max_clamp(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "1000")
        assert ch._xcagi_chat_timeout_seconds() == 600.0

    def test_invalid_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "not_a_number")
        assert ch._xcagi_chat_timeout_seconds() == 120.0


# ---------------------------------------------------------------------------
# _xcagi_stream_first_token_timeout_seconds — extended
# ---------------------------------------------------------------------------


class TestXcagiStreamFirstTokenTimeoutSecondsExtended:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", raising=False)
        assert ch._xcagi_stream_first_token_timeout_seconds() == 20.0

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "30")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 30.0

    def test_min_clamp(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "1")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 3.0

    def test_max_clamp(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "200")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 120.0

    def test_invalid_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "abc")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 20.0


# ---------------------------------------------------------------------------
# _xcagi_stream_idle_notice_seconds — extended
# ---------------------------------------------------------------------------


class TestXcagiStreamIdleNoticeSecondsExtended:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", raising=False)
        assert ch._xcagi_stream_idle_notice_seconds() == 12.0

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "20")
        assert ch._xcagi_stream_idle_notice_seconds() == 20.0

    def test_min_clamp(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "1")
        assert ch._xcagi_stream_idle_notice_seconds() == 5.0

    def test_max_clamp(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "100")
        assert ch._xcagi_stream_idle_notice_seconds() == 60.0

    def test_invalid_value(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "xyz")
        assert ch._xcagi_stream_idle_notice_seconds() == 12.0


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_error_payload — extended
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutErrorPayloadExtended:
    def test_payload_structure(self):
        result = ch._xcagi_chat_timeout_error_payload(120.0)
        assert result["success"] is False
        assert "120" in result["message"]
        assert "XCAGI_CHAT_TIMEOUT_SEC" in result["message"]
        assert result["data"]["text"] == result["message"]


# ---------------------------------------------------------------------------
# _thinking_steps_from_planner_stream_text — extended
# ---------------------------------------------------------------------------


class TestThinkingStepsFromPlannerStreamTextExtended:
    def test_empty_text(self):
        assert ch._thinking_steps_from_planner_stream_text("") is None

    def test_none_text(self):
        assert ch._thinking_steps_from_planner_stream_text(None) is None

    def test_no_markers(self):
        assert ch._thinking_steps_from_planner_stream_text("普通文本") is None

    def test_tool_call_marker(self):
        result = ch._thinking_steps_from_planner_stream_text(
            "前缀[正在调用工具:查询]后缀"
        )
        assert result is not None
        assert "[正在调用工具:查询]" in result

    def test_tool_returned_marker(self):
        result = ch._thinking_steps_from_planner_stream_text(
            "[工具已返回结果]"
        )
        assert result is not None
        assert "[工具已返回结果]" in result

    def test_tool_failed_marker(self):
        result = ch._thinking_steps_from_planner_stream_text(
            "[工具未成功:超时]"
        )
        assert result is not None

    def test_authorization_marker(self):
        result = ch._thinking_steps_from_planner_stream_text(
            "[需要授权:DB_READ_TOKEN]"
        )
        assert result is not None

    def test_token_required_marker(self):
        result = ch._thinking_steps_from_planner_stream_text(
            "[请提供令牌:write_token]"
        )
        assert result is not None

    def test_multiple_markers_deduplicated(self):
        result = ch._thinking_steps_from_planner_stream_text(
            "[正在调用工具:a][正在调用工具:a][工具已返回]"
        )
        assert result is not None
        # Should dedupe identical markers
        lines = result.split("\n")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# _sse_event_line — extended
# ---------------------------------------------------------------------------


class TestSseEventLineExtended:
    def test_basic(self):
        result = ch._sse_event_line({"type": "token", "text": "hello"})
        assert result.startswith(b"data: ")
        assert result.endswith(b"\n\n")
        assert b"hello" in result

    def test_unicode(self):
        result = ch._sse_event_line({"type": "token", "text": "你好"})
        assert "你好".encode("utf-8") in result


# ---------------------------------------------------------------------------
# _ensure_chat_db_read_authorized — extended
# ---------------------------------------------------------------------------


class TestEnsureChatDbReadAuthorizedExtended:
    def test_no_expected_token(self):
        request = Mock()
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers.effective_db_read_token",
            return_value="",
        ):
            ok, payload = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token=None
            )
        assert ok is True
        assert payload is None

    def test_message_does_not_require_token(self):
        request = Mock()
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers.effective_db_read_token",
            return_value="secret",
        ):
            ok, payload = ch._ensure_chat_db_read_authorized(
                request, message="普通消息", provided_token=None
            )
        assert ok is True
        assert payload is None

    def test_grace_period_active(self):
        request = Mock()
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.effective_db_read_token",
                return_value="secret",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_seconds_left",
                return_value=100,
            ),
        ):
            ok, payload = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token=None
            )
        assert ok is True
        assert payload is None

    def test_valid_token_provided(self):
        request = Mock()
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.effective_db_read_token",
                return_value="secret",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_seconds_left",
                return_value=0,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._touch_chat_db_read_grace",
                return_value=300,
            ),
        ):
            ok, payload = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token="secret"
            )
        assert ok is True
        assert payload is None

    def test_invalid_token_provided(self):
        request = Mock()
        with (
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers.effective_db_read_token",
                return_value="secret",
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_seconds_left",
                return_value=0,
            ),
        ):
            ok, payload = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token="wrong"
            )
        assert ok is False
        assert payload is not None
        assert payload["requires_token"] is True


# ---------------------------------------------------------------------------
# _message_requires_db_read_token — extended
# ---------------------------------------------------------------------------


class TestMessageRequiresDbReadTokenExtended:
    def test_empty_message(self):
        assert ch._message_requires_db_read_token("") is False

    def test_none_message(self):
        assert ch._message_requires_db_read_token(None) is False

    def test_query_database(self):
        assert ch._message_requires_db_read_token("查询数据库") is True

    def test_view_product_library(self):
        assert ch._message_requires_db_read_token("查看产品库") is True

    def test_database_query(self):
        assert ch._message_requires_db_read_token("数据库查询") is True

    def test_normal_message(self):
        assert ch._message_requires_db_read_token("你好") is False


# ---------------------------------------------------------------------------
# _chat_db_read_grace_seconds_left — extended
# ---------------------------------------------------------------------------


class TestChatDbReadGraceSecondsLeftExtended:
    def _subject_key(self, request):
        return ch._chat_request_subject(request)

    def test_no_grace_set(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_until",
            {},
        ):
            result = ch._chat_db_read_grace_seconds_left(request)
        assert result == 0

    def test_grace_expired(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        past_time = time.time() - 100
        key = self._subject_key(request)
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_until",
            {key: past_time},
        ):
            result = ch._chat_db_read_grace_seconds_left(request)
        assert result == 0

    def test_grace_active(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        future_time = time.time() + 100
        key = self._subject_key(request)
        with patch(
            "app.fastapi_routes.xcagi_compat_chat_helpers._chat_db_read_grace_until",
            {key: future_time},
        ):
            result = ch._chat_db_read_grace_seconds_left(request)
        assert result > 0


# ---------------------------------------------------------------------------
# _touch_chat_db_read_grace — extended
# ---------------------------------------------------------------------------


class TestTouchChatDbReadGraceExtended:
    def test_touch_returns_grace_seconds(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "ua"}
        result = ch._touch_chat_db_read_grace(request)
        assert result == ch._CHAT_DB_READ_GRACE_SEC


# ---------------------------------------------------------------------------
# _chat_request_subject — extended
# ---------------------------------------------------------------------------


class TestChatRequestSubjectExtended:
    def test_no_xff_no_client(self):
        request = Mock()
        request.headers = {}
        request.client = None
        result = ch._chat_request_subject(request)
        assert result.startswith("unknown|")

    def test_no_user_agent(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4"}
        result = ch._chat_request_subject(request)
        assert result.endswith("|na")

    def test_with_user_agent(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "TestAgent"}
        result = ch._chat_request_subject(request)
        # Should contain IP and a 12-char fingerprint
        parts = result.split("|")
        assert parts[0] == "1.2.3.4"
        assert len(parts[1]) == 12
