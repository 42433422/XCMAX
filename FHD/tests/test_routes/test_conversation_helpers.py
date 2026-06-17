"""conversation/helpers 测试 — 覆盖 DB 读令牌、Excel 路径提取、运行时上下文合并、错误映射等。"""

from __future__ import annotations

import os
import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.fastapi_routes.domains.conversation import helpers


# ---------------------------------------------------------------------------
# _chat_request_subject
# ---------------------------------------------------------------------------


class TestChatRequestSubject:
    def test_from_xff_header(self):
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2"}
        req.client = None
        subject = helpers._chat_request_subject(req)
        assert subject.startswith("10.0.0.1|")

    def test_from_client_host(self):
        req = MagicMock(spec=Request)
        req.headers = {}
        client = MagicMock()
        client.host = "192.168.1.1"
        req.client = client
        subject = helpers._chat_request_subject(req)
        assert subject.startswith("192.168.1.1|")

    def test_fallback_unknown(self):
        req = MagicMock(spec=Request)
        req.headers = {}
        req.client = None
        subject = helpers._chat_request_subject(req)
        assert subject.startswith("unknown|")

    def test_ua_fingerprint(self):
        req = MagicMock(spec=Request)
        req.headers = {"user-agent": "Mozilla/5.0"}
        req.client = None
        subject = helpers._chat_request_subject(req)
        parts = subject.split("|")
        assert len(parts) == 2
        assert len(parts[1]) == 12  # SHA1 前 12 字符

    def test_no_ua(self):
        req = MagicMock(spec=Request)
        req.headers = {}
        req.client = None
        subject = helpers._chat_request_subject(req)
        assert subject.endswith("|na")


# ---------------------------------------------------------------------------
# _message_requires_db_read_token
# ---------------------------------------------------------------------------


class TestMessageRequiresDbReadToken:
    def test_empty_message(self):
        assert helpers._message_requires_db_read_token("") is False

    def test_none_message(self):
        assert helpers._message_requires_db_read_token(None) is False

    def test_db_read_intent(self):
        assert helpers._message_requires_db_read_token("查看数据库") is True

    def test_db_read_intent_reversed(self):
        assert helpers._message_requires_db_read_token("数据库查看") is True

    def test_normal_message(self):
        assert helpers._message_requires_db_read_token("你好") is False

    def test_query_product_db(self):
        assert helpers._message_requires_db_read_token("查询产品库") is True


# ---------------------------------------------------------------------------
# _chat_read_token_required_payload
# ---------------------------------------------------------------------------


class TestChatReadTokenRequiredPayload:
    def test_structure(self):
        payload = helpers._chat_read_token_required_payload("test")
        assert payload["requires_token"] is True
        assert payload["token_name"] == "DB_READ_TOKEN"
        assert "token_description" in payload
        assert "message" in payload


# ---------------------------------------------------------------------------
# _ensure_chat_db_read_authorized
# ---------------------------------------------------------------------------


class TestEnsureChatDbReadAuthorized:
    def test_no_expected_token(self):
        with patch("app.fastapi_routes.domains.conversation.helpers.effective_db_read_token", return_value=""):
            req = MagicMock(spec=Request)
            ok, payload = helpers._ensure_chat_db_read_authorized(req, message="查看数据库", provided_token=None)
            assert ok is True
            assert payload is None

    def test_non_db_read_message(self):
        with patch("app.fastapi_routes.domains.conversation.helpers.effective_db_read_token", return_value="secret"):
            req = MagicMock(spec=Request)
            ok, payload = helpers._ensure_chat_db_read_authorized(req, message="你好", provided_token=None)
            assert ok is True

    def test_grace_period_active(self):
        with patch("app.fastapi_routes.domains.conversation.helpers.effective_db_read_token", return_value="secret"):
            req = MagicMock(spec=Request)
            with patch.object(helpers, "_chat_db_read_grace_seconds_left", return_value=100):
                ok, payload = helpers._ensure_chat_db_read_authorized(req, message="查看数据库", provided_token=None)
                assert ok is True

    def test_correct_token(self):
        with patch("app.fastapi_routes.domains.conversation.helpers.effective_db_read_token", return_value="secret"):
            req = MagicMock(spec=Request)
            with patch.object(helpers, "_chat_db_read_grace_seconds_left", return_value=0), \
                 patch.object(helpers, "_touch_chat_db_read_grace", return_value=300):
                ok, payload = helpers._ensure_chat_db_read_authorized(req, message="查看数据库", provided_token="secret")
                assert ok is True

    def test_wrong_token(self):
        with patch("app.fastapi_routes.domains.conversation.helpers.effective_db_read_token", return_value="secret"):
            req = MagicMock(spec=Request)
            with patch.object(helpers, "_chat_db_read_grace_seconds_left", return_value=0):
                ok, payload = helpers._ensure_chat_db_read_authorized(req, message="查看数据库", provided_token="wrong")
                assert ok is False
                assert payload is not None
                assert payload["requires_token"] is True


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc
# ---------------------------------------------------------------------------


class TestXcagiChatHttpExc:
    def test_timeout_error(self):
        exc = helpers._xcagi_chat_http_exc(TimeoutError("timeout"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 504

    def test_authentication_error(self):
        from openai import AuthenticationError
        exc = helpers._xcagi_chat_http_exc(AuthenticationError(message="bad key", response=MagicMock(), body=None))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 401

    def test_rate_limit_error(self):
        from openai import RateLimitError
        exc = helpers._xcagi_chat_http_exc(RateLimitError(message="slow down", response=MagicMock(), body=None))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 429

    def test_api_connection_error(self):
        from openai import APIConnectionError
        exc = helpers._xcagi_chat_http_exc(APIConnectionError(message="no connect", request=MagicMock()))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 503

    def test_api_error(self):
        from openai import APIError
        exc = helpers._xcagi_chat_http_exc(APIError(message="generic", request=MagicMock(), body=None))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 502

    def test_runtime_error(self):
        exc = helpers._xcagi_chat_http_exc(RuntimeError("service down"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 503

    def test_value_error_insufficient_balance(self):
        exc = helpers._xcagi_chat_http_exc(ValueError("余额不足"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 402

    def test_value_error_platform_error(self):
        exc = helpers._xcagi_chat_http_exc(ValueError("平台错误"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 502

    def test_generic_error(self):
        exc = helpers._xcagi_chat_http_exc(Exception("unknown"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 500


# ---------------------------------------------------------------------------
# _xcagi_compat_reply_payload
# ---------------------------------------------------------------------------


class TestXcagiCompatReplyPayload:
    def test_string_reply(self):
        result = helpers._xcagi_compat_reply_payload("Hello")
        assert result["success"] is True
        assert result["response"] == "Hello"
        assert result["data"]["text"] == "Hello"

    def test_dict_reply(self):
        result = helpers._xcagi_compat_reply_payload({"response": "Hi", "thinking_steps": "step1"})
        assert result["response"] == "Hi"
        assert result["data"]["thinking_steps"] == "step1"

    def test_dict_with_text_key(self):
        result = helpers._xcagi_compat_reply_payload({"text": "World"})
        assert result["response"] == "World"

    def test_runtime_context_update(self):
        result = helpers._xcagi_compat_reply_payload("ok", runtime_context_update={"key": "val"})
        assert result["data"]["runtime_context"] == {"key": "val"}

    def test_kitten_attachments(self):
        result = helpers._xcagi_compat_reply_payload("ok", kitten_attachments={"chart": {"type": "bar"}})
        assert result["data"]["chart"] == {"type": "bar"}

    def test_kitten_attachments_none_skipped(self):
        result = helpers._xcagi_compat_reply_payload("ok", kitten_attachments={"chart": None})
        assert "chart" not in result["data"]


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_message
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromMessage:
    def test_xlsx_in_message(self):
        paths = helpers._extract_excel_paths_from_message("请分析 @data/test.xlsx 的数据")
        assert len(paths) == 1
        assert "data/test.xlsx" in paths[0]

    def test_xlsm_in_message(self):
        paths = helpers._extract_excel_paths_from_message("打开 report.xlsm 文件")
        assert len(paths) == 1

    def test_no_excel(self):
        paths = helpers._extract_excel_paths_from_message("普通消息")
        assert paths == []

    def test_multiple_paths(self):
        paths = helpers._extract_excel_paths_from_message("比较 a.xlsx 和 b.xlsx")
        assert len(paths) == 2

    def test_dedup(self):
        paths = helpers._extract_excel_paths_from_message("a.xlsx a.xlsx")
        assert len(paths) == 1

    def test_backslash_converted(self):
        paths = helpers._extract_excel_paths_from_message("data\\test.xlsx")
        assert paths[0] == "data/test.xlsx"


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_context
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromContext:
    def test_excel_file_path(self):
        ctx = {"excel_file_path": "data/test.xlsx"}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert "data/test.xlsx" in paths

    def test_excel_file_paths(self):
        ctx = {"excel_file_paths": ["a.xlsx", "b.xlsx"]}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert len(paths) == 2

    def test_excel_analysis(self):
        ctx = {"excel_analysis": {"file_path": "c.xlsx"}}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert "c.xlsx" in paths

    def test_excel_analysis_preview(self):
        ctx = {"excel_analysis": {"preview_data": {"file_path": "d.xlsx"}}}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert "d.xlsx" in paths

    def test_non_excel_ignored(self):
        ctx = {"excel_file_path": "data/test.csv"}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert paths == []

    def test_empty_context(self):
        paths = helpers._extract_excel_paths_from_context({})
        assert paths == []


# ---------------------------------------------------------------------------
# _merge_runtime_context_with_message_paths
# ---------------------------------------------------------------------------


class TestMergeRuntimeContextWithMessagePaths:
    def test_no_paths(self):
        ctx, found = helpers._merge_runtime_context_with_message_paths({}, "普通消息")
        assert found == []
        assert "excel_file_path" not in ctx

    def test_message_path_only(self):
        ctx, found = helpers._merge_runtime_context_with_message_paths({}, "分析 test.xlsx")
        assert "test.xlsx" in found[0]
        assert ctx["excel_file_path"] == found[0]

    def test_context_path_only(self):
        ctx, found = helpers._merge_runtime_context_with_message_paths(
            {"excel_file_path": "ctx.xlsx"}, "普通消息"
        )
        assert found == []
        assert "excel_file_paths" in ctx

    def test_merge_dedup_by_basename(self):
        ctx, found = helpers._merge_runtime_context_with_message_paths(
            {"excel_file_path": "/full/path/test.xlsx"}, "分析 test.xlsx"
        )
        # Should prefer context path when basename matches
        all_paths = ctx.get("excel_file_paths", [])
        assert len(all_paths) >= 1


# ---------------------------------------------------------------------------
# _looks_like_vector_request
# ---------------------------------------------------------------------------


class TestLooksLikeVectorRequest:
    def test_vector_keyword(self):
        assert helpers._looks_like_vector_request("建立向量索引") is True

    def test_embedding_keyword(self):
        assert helpers._looks_like_vector_request("embedding search") is True

    def test_semantic_search(self):
        assert helpers._looks_like_vector_request("semantic search") is True

    def test_normal_message(self):
        assert helpers._looks_like_vector_request("你好") is False

    def test_empty(self):
        assert helpers._looks_like_vector_request("") is False


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_seconds
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_TIMEOUT_SEC", raising=False)
        assert helpers._xcagi_chat_timeout_seconds() == 120.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "60")
        assert helpers._xcagi_chat_timeout_seconds() == 60.0

    def test_clamped_min(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "1")
        assert helpers._xcagi_chat_timeout_seconds() == 5.0

    def test_clamped_max(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "9999")
        assert helpers._xcagi_chat_timeout_seconds() == 600.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_TIMEOUT_SEC", "abc")
        assert helpers._xcagi_chat_timeout_seconds() == 120.0


# ---------------------------------------------------------------------------
# _xcagi_stream_first_token_timeout_seconds
# ---------------------------------------------------------------------------


class TestXcagiStreamFirstTokenTimeoutSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", raising=False)
        assert helpers._xcagi_stream_first_token_timeout_seconds() == 20.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "30")
        assert helpers._xcagi_stream_first_token_timeout_seconds() == 30.0

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC", "bad")
        assert helpers._xcagi_stream_first_token_timeout_seconds() == 20.0


# ---------------------------------------------------------------------------
# _xcagi_stream_idle_notice_seconds
# ---------------------------------------------------------------------------


class TestXcagiStreamIdleNoticeSeconds:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", raising=False)
        assert helpers._xcagi_stream_idle_notice_seconds() == 12.0

    def test_custom(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CHAT_STREAM_IDLE_NOTICE_SEC", "15")
        assert helpers._xcagi_stream_idle_notice_seconds() == 15.0


# ---------------------------------------------------------------------------
# _xcagi_chat_timeout_error_payload
# ---------------------------------------------------------------------------


class TestXcagiChatTimeoutErrorPayload:
    def test_structure(self):
        payload = helpers._xcagi_chat_timeout_error_payload(120.0)
        assert payload["success"] is False
        assert "120" in payload["message"]
        assert "XCAGI_CHAT_TIMEOUT_SEC" in payload["message"]


# ---------------------------------------------------------------------------
# _sse_event_line
# ---------------------------------------------------------------------------


class TestSseEventLine:
    def test_format(self):
        line = helpers._sse_event_line({"type": "token", "text": "hi"})
        assert line.startswith(b"data: ")
        assert line.endswith(b"\n\n")
        assert b'"type"' in line


# ---------------------------------------------------------------------------
# _thinking_steps_from_planner_stream_text
# ---------------------------------------------------------------------------


class TestThinkingStepsFromPlannerStreamText:
    def test_empty(self):
        assert helpers._thinking_steps_from_planner_stream_text("") is None

    def test_none(self):
        assert helpers._thinking_steps_from_planner_stream_text(None) is None

    def test_tool_call(self):
        text = "一些文本 [正在调用工具:search] 结果"
        result = helpers._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "正在调用工具:search" in result

    def test_tool_return(self):
        text = "[工具已返回] 数据"
        result = helpers._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "工具已返回" in result

    def test_tool_failed(self):
        text = "[工具未成功] 错误"
        result = helpers._thinking_steps_from_planner_stream_text(text)
        assert result is not None

    def test_auth_required(self):
        text = "[需要授权:DB_WRITE_TOKEN] 请提供令牌"
        result = helpers._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert "需要授权" in result

    def test_no_tool_markers(self):
        text = "普通回复文本，没有工具调用"
        result = helpers._thinking_steps_from_planner_stream_text(text)
        assert result is None

    def test_dedup(self):
        text = "[正在调用工具:search] [正在调用工具:search]"
        result = helpers._thinking_steps_from_planner_stream_text(text)
        assert result is not None
        assert result.count("正在调用工具:search") == 1


# ---------------------------------------------------------------------------
# strip_planner_stream_markers
# ---------------------------------------------------------------------------


class TestStripPlannerStreamMarkers:
    def test_splits_user_text_and_thinking(self):
        from app.application.planner_display_markers import strip_planner_stream_markers

        merged = "你好 [正在调用工具:excel.read] 已读完。"
        user_text, thinking = strip_planner_stream_markers(merged)
        assert "[正在调用工具" not in user_text
        assert "你好" in user_text
        assert "已读完" in user_text
        assert thinking is not None
        assert "正在调用工具:excel.read" in thinking

    def test_empty_merged(self):
        from app.application.planner_display_markers import strip_planner_stream_markers

        user_text, thinking = strip_planner_stream_markers("")
        assert user_text == ""
        assert thinking is None


# ---------------------------------------------------------------------------
# XcagiCompatChatBody
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBody:
    def test_basic_construction(self):
        body = helpers.XcagiCompatChatBody(message="hello")
        assert body.message == "hello"
        assert body.context is None
        assert body.system_prompt is None

    def test_alias_user_message(self):
        body = helpers.XcagiCompatChatBody(user_message="hi")
        assert body.message == "hi"

    def test_alias_content(self):
        body = helpers.XcagiCompatChatBody(content="text")
        assert body.message == "text"

    def test_alias_query(self):
        body = helpers.XcagiCompatChatBody(query="q")
        assert body.message == "q"

    def test_context_alias(self):
        body = helpers.XcagiCompatChatBody(message="m", runtime_context={"k": "v"})
        assert body.context == {"k": "v"}


# ---------------------------------------------------------------------------
# XcagiCompatChatBatchBody
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBatchBody:
    def test_basic(self):
        body = helpers.XcagiCompatChatBatchBody(messages=["a", "b"])
        assert body.messages == ["a", "b"]
        assert body.user_id is None
