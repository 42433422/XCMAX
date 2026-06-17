"""Tests for app.fastapi_routes.xcagi_compat_chat_helpers — pure helper functions and models."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes import xcagi_compat_chat_helpers as ch


# ---------------------------------------------------------------------------
# XcagiCompatChatBody
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBody:
    def test_basic_creation(self):
        body = ch.XcagiCompatChatBody(message="hello")
        assert body.message == "hello"
        assert body.context is None
        assert body.system_prompt is None
        assert body.mode is None
        assert body.db_read_token is None
        assert body.db_write_token is None

    def test_alias_message(self):
        body = ch.XcagiCompatChatBody(user_message="hi")
        assert body.message == "hi"

    def test_alias_content(self):
        body = ch.XcagiCompatChatBody(content="test")
        assert body.message == "test"

    def test_alias_text(self):
        body = ch.XcagiCompatChatBody(text="msg")
        assert body.message == "msg"

    def test_alias_query(self):
        body = ch.XcagiCompatChatBody(query="search")
        assert body.message == "search"

    def test_alias_context(self):
        body = ch.XcagiCompatChatBody(message="hi", runtime_context={"k": "v"})
        assert body.context == {"k": "v"}

    def test_alias_system_prompt(self):
        body = ch.XcagiCompatChatBody(message="hi", system="sys")
        assert body.system_prompt == "sys"

    def test_alias_instructions(self):
        body = ch.XcagiCompatChatBody(message="hi", instructions="instr")
        assert body.system_prompt == "instr"

    def test_alias_mode(self):
        body = ch.XcagiCompatChatBody(message="hi", llm_mode="online")
        assert body.mode == "online"

    def test_extra_fields_ignored(self):
        body = ch.XcagiCompatChatBody(message="hi", unknown="x")
        assert not hasattr(body, "unknown")

    def test_empty_message_fails(self):
        with pytest.raises(Exception):
            ch.XcagiCompatChatBody(message="")


# ---------------------------------------------------------------------------
# XcagiCompatChatBatchBody
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBatchBody:
    def test_basic(self):
        body = ch.XcagiCompatChatBatchBody(messages=["hello", "world"])
        assert body.messages == ["hello", "world"]
        assert body.user_id is None
        assert body.source is None

    def test_default_messages(self):
        body = ch.XcagiCompatChatBatchBody()
        assert body.messages == []


# ---------------------------------------------------------------------------
# _chat_request_subject
# ---------------------------------------------------------------------------


class TestChatRequestSubject:
    def test_with_xff(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8", "user-agent": "TestAgent/1.0"}
        result = ch._chat_request_subject(request)
        assert result.startswith("1.2.3.4|")

    def test_with_client_host(self):
        request = MagicMock()
        request.headers = {"user-agent": "TestAgent/1.0"}
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        result = ch._chat_request_subject(request)
        assert result.startswith("10.0.0.1|")

    def test_no_ip(self):
        request = MagicMock()
        request.headers = {"user-agent": "TestAgent/1.0"}
        request.client = None
        result = ch._chat_request_subject(request)
        assert result.startswith("unknown|")

    def test_no_ua(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": ""}
        result = ch._chat_request_subject(request)
        assert result.endswith("|na")


# ---------------------------------------------------------------------------
# _chat_db_read_grace_seconds_left / _touch_chat_db_read_grace
# ---------------------------------------------------------------------------


class TestChatDbReadGrace:
    @pytest.fixture(autouse=True)
    def _clear_grace(self):
        ch._chat_db_read_grace_until.clear()
        yield
        ch._chat_db_read_grace_until.clear()

    def test_no_grace(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        assert ch._chat_db_read_grace_seconds_left(request) == 0

    def test_touch_and_check(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        ch._touch_chat_db_read_grace(request)
        assert ch._chat_db_read_grace_seconds_left(request) > 0

    def test_expired_grace(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        ch._touch_chat_db_read_grace(request)
        # Manually expire
        subject = ch._chat_request_subject(request)
        ch._chat_db_read_grace_until[subject] = time.time() - 1
        assert ch._chat_db_read_grace_seconds_left(request) == 0


# ---------------------------------------------------------------------------
# _message_requires_db_read_token
# ---------------------------------------------------------------------------


class TestMessageRequiresDbReadToken:
    def test_empty(self):
        assert ch._message_requires_db_read_token("") is False

    def test_none(self):
        assert ch._message_requires_db_read_token(None) is False

    def test_query_db(self):
        assert ch._message_requires_db_read_token("查询数据库") is True

    def test_read_product_db(self):
        assert ch._message_requires_db_read_token("读取产品库") is True

    def test_normal_message(self):
        assert ch._message_requires_db_read_token("今天天气怎么样") is False

    def test_db_first(self):
        assert ch._message_requires_db_read_token("数据库查看") is True


# ---------------------------------------------------------------------------
# _chat_read_token_required_payload
# ---------------------------------------------------------------------------


class TestChatReadTokenRequiredPayload:
    def test_structure(self):
        result = ch._chat_read_token_required_payload("test")
        assert result["requires_token"] is True
        assert result["token_name"] == "DB_READ_TOKEN"
        assert "token_description" in result


# ---------------------------------------------------------------------------
# _ensure_chat_db_read_authorized
# ---------------------------------------------------------------------------


class TestEnsureChatDbReadAuthorized:
    @pytest.fixture(autouse=True)
    def _clear_grace(self):
        ch._chat_db_read_grace_until.clear()
        yield
        ch._chat_db_read_grace_until.clear()

    def test_no_token_configured(self):
        with patch.object(ch, "effective_db_read_token", return_value=""):
            ok, req = ch._ensure_chat_db_read_authorized(
                MagicMock(), message="查询数据库", provided_token=None
            )
            assert ok is True

    def test_message_does_not_require_token(self):
        with patch.object(ch, "effective_db_read_token", return_value="secret"):
            ok, req = ch._ensure_chat_db_read_authorized(
                MagicMock(), message="hello", provided_token=None
            )
            assert ok is True

    def test_grace_period_active(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        with patch.object(ch, "effective_db_read_token", return_value="secret"):
            ch._touch_chat_db_read_grace(request)
            ok, req = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token=None
            )
            assert ok is True

    def test_correct_token(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        with patch.object(ch, "effective_db_read_token", return_value="secret"):
            ok, req = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token="secret"
            )
            assert ok is True

    def test_wrong_token(self):
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4", "user-agent": "test"}
        with patch.object(ch, "effective_db_read_token", return_value="secret"), \
             patch.object(ch, "_chat_db_read_grace_seconds_left", return_value=0):
            ok, req = ch._ensure_chat_db_read_authorized(
                request, message="查询数据库", provided_token="wrong"
            )
            assert ok is False
            assert req is not None


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc
# ---------------------------------------------------------------------------


class TestXcagiChatHttpExc:
    def test_timeout_error(self):
        exc = TimeoutError("timeout")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 504

    def test_authentication_error(self):
        from openai import AuthenticationError
        exc = AuthenticationError(message="bad key", response=MagicMock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 401

    def test_rate_limit_error(self):
        from openai import RateLimitError
        exc = RateLimitError(message="limited", response=MagicMock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 429

    def test_api_connection_error(self):
        from openai import APIConnectionError
        exc = APIConnectionError(message="no connection", request=MagicMock())
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503

    def test_api_error(self):
        from openai import APIError
        exc = APIError(message="api error", request=MagicMock(), body=None)
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_runtime_error(self):
        exc = RuntimeError("runtime fail")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 503

    def test_value_error_insufficient_balance(self):
        exc = ValueError("余额不足")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 402

    def test_value_error_402(self):
        exc = ValueError("error 402 payment required")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 402

    def test_value_error_platform(self):
        exc = ValueError("平台错误 xxx")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 502

    def test_generic_error(self):
        exc = Exception("unknown")
        result = ch._xcagi_chat_http_exc(exc)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# _xcagi_compat_reply_payload
# ---------------------------------------------------------------------------


class TestXcagiCompatReplyPayload:
    def test_string_reply(self):
        with patch("app.application.workflow.legacy_chat_adapter.get_last_tool_result", return_value=None, create=True):
            result = ch._xcagi_compat_reply_payload("hello")
            assert result["success"] is True
            assert result["response"] == "hello"

    def test_dict_reply(self):
        with patch("app.application.workflow.legacy_chat_adapter.get_last_tool_result", return_value=None, create=True):
            result = ch._xcagi_compat_reply_payload({"response": "world", "thinking_steps": "step1"})
            assert result["response"] == "world"
            assert result["data"]["thinking_steps"] == "step1"

    def test_dict_reply_text_key(self):
        with patch("app.application.workflow.legacy_chat_adapter.get_last_tool_result", return_value=None, create=True):
            result = ch._xcagi_compat_reply_payload({"text": "msg"})
            assert result["response"] == "msg"

    def test_with_runtime_context(self):
        with patch("app.application.workflow.legacy_chat_adapter.get_last_tool_result", return_value=None, create=True):
            result = ch._xcagi_compat_reply_payload("hello", runtime_context_update={"k": "v"})
            assert result["data"]["runtime_context"] == {"k": "v"}

    def test_with_kitten_attachments(self):
        with patch("app.application.workflow.legacy_chat_adapter.get_last_tool_result", return_value=None, create=True):
            result = ch._xcagi_compat_reply_payload("hello", kitten_attachments={"chart": "data"})
            assert result["data"]["chart"] == "data"

    def test_kitten_attachments_none_skipped(self):
        with patch("app.application.workflow.legacy_chat_adapter.get_last_tool_result", return_value=None, create=True):
            result = ch._xcagi_compat_reply_payload("hello", kitten_attachments={"chart": None})
            assert "chart" not in result["data"]


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_message
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromMessage:
    def test_xlsx(self):
        result = ch._extract_excel_paths_from_message("请分析 @data/test.xlsx 的数据")
        assert len(result) == 1
        assert "data/test.xlsx" in result[0]

    def test_xlsm(self):
        result = ch._extract_excel_paths_from_message("打开 report.xlsm")
        assert len(result) == 1

    def test_xls(self):
        result = ch._extract_excel_paths_from_message("查看 old.xls")
        assert len(result) == 1

    def test_no_excel(self):
        result = ch._extract_excel_paths_from_message("今天天气不错")
        assert result == []

    def test_multiple(self):
        result = ch._extract_excel_paths_from_message("对比 a.xlsx 和 b.xlsx")
        assert len(result) == 2

    def test_dedup(self):
        result = ch._extract_excel_paths_from_message("a.xlsx a.xlsx")
        assert len(result) == 1

    def test_empty(self):
        result = ch._extract_excel_paths_from_message("")
        assert result == []


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_context
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromContext:
    def test_excel_file_path(self):
        ctx = {"excel_file_path": "data/test.xlsx"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_excel_file_paths(self):
        ctx = {"excel_file_paths": ["a.xlsx", "b.xlsx"]}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 2

    def test_excel_analysis(self):
        ctx = {"excel_analysis": {"file_path": "c.xlsx"}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_excel_analysis_preview(self):
        ctx = {"excel_analysis": {"preview_data": {"file_path": "d.xlsx"}}}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 1

    def test_non_excel_skipped(self):
        ctx = {"excel_file_path": "data/test.csv"}
        result = ch._extract_excel_paths_from_context(ctx)
        assert len(result) == 0

    def test_empty(self):
        result = ch._extract_excel_paths_from_context({})
        assert result == []


# ---------------------------------------------------------------------------
# _merge_runtime_context_with_message_paths
# ---------------------------------------------------------------------------


class TestMergeRuntimeContextWithMessagePaths:
    def test_no_paths(self):
        ctx, found = ch._merge_runtime_context_with_message_paths({}, "hello")
        assert found == []
        assert "excel_file_path" not in ctx

    def test_message_path_only(self):
        ctx, found = ch._merge_runtime_context_with_message_paths({}, "分析 test.xlsx")
        assert len(found) == 1
        assert ctx["excel_file_path"] == found[0]

    def test_context_path_only(self):
        ctx, found = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "data/test.xlsx"}, "hello"
        )
        assert len(found) == 0
        assert ctx["excel_file_paths"] == ["data/test.xlsx"]

    def test_both_sources(self):
        ctx, found = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "data/test.xlsx"}, "分析 other.xlsx"
        )
        assert len(found) == 1
        assert len(ctx["excel_file_paths"]) == 2

    def test_same_basename_merged(self):
        ctx, found = ch._merge_runtime_context_with_message_paths(
            {"excel_file_path": "dir/test.xlsx"}, "分析 test.xlsx"
        )
        # Context path should be preferred when basename matches
        assert len(ctx["excel_file_paths"]) >= 1


# ---------------------------------------------------------------------------
# _looks_like_vector_request
# ---------------------------------------------------------------------------


class TestLooksLikeVectorRequest:
    def test_vector_keyword(self):
        assert ch._looks_like_vector_request("建立向量索引") is True

    def test_embedding_keyword(self):
        assert ch._looks_like_vector_request("embedding search") is True

    def test_semantic_search(self):
        assert ch._looks_like_vector_request("semantic search") is True

    def test_normal_message(self):
        assert ch._looks_like_vector_request("今天天气") is False

    def test_empty(self):
        assert ch._looks_like_vector_request("") is False


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_seconds
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_TIMEOUT_SEC", raising=False)
        assert ch._xcagi_chat_timeout_seconds() == 120.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "60")
        assert ch._xcagi_chat_timeout_seconds() == 60.0

    def test_clamped_min(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "1")
        assert ch._xcagi_chat_timeout_seconds() == 5.0

    def test_clamped_max(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "9999")
        assert ch._xcagi_chat_timeout_seconds() == 600.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "bad")
        assert ch._xcagi_chat_timeout_seconds() == 120.0


# ---------------------------------------------------------------------------
# _xcagi_stream_first_token_timeout_seconds
# ---------------------------------------------------------------------------


class TestXcagiStreamFirstTokenTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", raising=False)
        assert ch._xcagi_stream_first_token_timeout_seconds() == 20.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "30")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 30.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "bad")
        assert ch._xcagi_stream_first_token_timeout_seconds() == 20.0


# ---------------------------------------------------------------------------
# _xcagi_stream_idle_notice_seconds
# ---------------------------------------------------------------------------


class TestXcagiStreamIdleNoticeSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", raising=False)
        assert ch._xcagi_stream_idle_notice_seconds() == 12.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "20")
        assert ch._xcagi_stream_idle_notice_seconds() == 20.0


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_error_payload
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutErrorPayload:
    def test_structure(self):
        result = ch._xcagi_chat_timeout_error_payload(120.0)
        assert result["success"] is False
        assert "120" in result["message"]
        assert "XCAGI_CHAT_TIMEOUT_SEC" in result["message"]


# ---------------------------------------------------------------------------
# _sse_event_line
# ---------------------------------------------------------------------------


class TestSseEventLine:
    def test_basic(self):
        result = ch._sse_event_line({"type": "token", "text": "hello"})
        assert result.startswith(b"data: ")
        assert result.endswith(b"\n\n")
        assert b"hello" in result


# ---------------------------------------------------------------------------
# _thinking_steps_from_planner_stream_text
# ---------------------------------------------------------------------------


class TestThinkingStepsFromPlannerStreamText:
    def test_tool_call(self):
        text = "[正在调用工具: search] 结果 [工具已返回]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "正在调用工具" in result

    def test_empty(self):
        result = ch._thinking_steps_from_planner_stream_text("")
        assert result is None

    def test_none(self):
        result = ch._thinking_steps_from_planner_stream_text(None)
        assert result is None

    def test_no_tool_markers(self):
        result = ch._thinking_steps_from_planner_stream_text("普通文本")
        assert result is None

    def test_auth_required(self):
        text = "[需要授权: DB_WRITE_TOKEN]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "需要授权" in result

    def test_tool_failed(self):
        text = "[工具未成功: timeout]"
        result = ch._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "工具未成功" in result
