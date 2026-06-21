from __future__ import annotations

"""Branch-coverage ramp for app.fastapi_routes.domains.conversation.helpers.

Targets the 35 missing branches (80.3% → higher) identified in coverage_new.json.
"""

import asyncio
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from app.fastapi_routes.domains.conversation import helpers
from app.fastapi_routes.domains.conversation.helpers import (
    XcagiCompatChatBody,
    _chat_db_read_grace_seconds_left,
    _chat_request_subject,
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _extract_excel_paths_from_context,
    _extract_excel_paths_from_message,
    _merge_runtime_context_with_message_paths,
    _message_requires_db_read_token,
    _thinking_steps_from_planner_stream_text,
    _touch_chat_db_read_grace,
    _xcagi_chat_http_exc,
    _xcagi_chat_timeout_seconds,
    _xcagi_compat_reply_payload,
    _xcagi_stream_first_token_timeout_seconds,
    strip_planner_stream_markers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_request(headers: dict | None = None, client_host: str | None = None) -> MagicMock:
    req = MagicMock(spec=Request)
    req.headers = MagicMock()
    req.headers.get = lambda k, d=None: (headers or {}).get(k, d)
    if client_host is not None:
        client = MagicMock()
        client.host = client_host
        req.client = client
    else:
        req.client = None
    return req


# ===========================================================================
# 1. _chat_request_subject — missing branches 249-250, 252-253
# ===========================================================================


class TestChatRequestSubjectBranches:
    def test_xff_multi_comma(self):
        req = _fake_request({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
        s = _chat_request_subject(req)
        assert s.startswith("1.2.3.4|")

    def test_xff_empty_falls_to_client(self):
        req = _fake_request({"x-forwarded-for": "  "}, client_host="10.0.0.2")
        s = _chat_request_subject(req)
        assert s.startswith("10.0.0.2|")

    def test_no_ip_no_client_host(self):
        req = _fake_request({})
        req.client = None
        s = _chat_request_subject(req)
        assert s.startswith("unknown|")

    def test_no_user_agent_ua_fingerprint_na(self):
        req = _fake_request({})
        req.client = None
        s = _chat_request_subject(req)
        assert s.endswith("|na")


# ===========================================================================
# 2. _chat_db_read_grace_seconds_left — branches 269-280
# ===========================================================================


class TestGraceSeconds:
    def test_grace_not_yet_set_returns_zero(self):
        req = _fake_request({}, client_host="192.0.0.1")
        # ensure no grace set for this IP
        helpers._chat_db_read_grace_until.clear()
        assert _chat_db_read_grace_seconds_left(req) == 0

    def test_grace_in_future_returns_positive(self):
        req = _fake_request({}, client_host="192.0.0.2")
        helpers._chat_db_read_grace_until.clear()
        _touch_chat_db_read_grace(req)
        secs = _chat_db_read_grace_seconds_left(req)
        assert secs > 0

    def test_grace_expired_cleans_up_and_returns_zero(self):
        req = _fake_request({}, client_host="192.0.0.3")
        subj = _chat_request_subject(req)
        helpers._chat_db_read_grace_until[subj] = time.time() - 1
        assert _chat_db_read_grace_seconds_left(req) == 0
        assert subj not in helpers._chat_db_read_grace_until


# ===========================================================================
# 3. _ensure_chat_db_read_authorized branches (lines 273-281)
# ===========================================================================


class TestEnsureChatDbReadAuthorized:
    def test_no_expected_token_always_ok(self):
        req = _fake_request({})
        with patch(
            "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
            return_value="",
        ):
            ok, payload = _ensure_chat_db_read_authorized(
                req, message="查询数据库", provided_token=None
            )
        assert ok is True
        assert payload is None

    def test_message_not_db_intent_always_ok(self):
        req = _fake_request({})
        with patch(
            "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
            return_value="secret",
        ):
            ok, payload = _ensure_chat_db_read_authorized(req, message="你好", provided_token=None)
        assert ok is True
        assert payload is None

    def test_grace_period_active_ok(self):
        req = _fake_request({}, client_host="192.1.0.1")
        _touch_chat_db_read_grace(req)
        with patch(
            "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
            return_value="sec",
        ):
            ok, payload = _ensure_chat_db_read_authorized(
                req, message="查询数据库", provided_token=None
            )
        assert ok is True

    def test_correct_token_grants_access(self):
        req = _fake_request({}, client_host="192.1.0.99")
        helpers._chat_db_read_grace_until.clear()
        with patch(
            "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
            return_value="mytoken",
        ):
            ok, payload = _ensure_chat_db_read_authorized(
                req, message="查询数据库", provided_token="mytoken"
            )
        assert ok is True
        assert payload is None

    def test_wrong_token_returns_false(self):
        req = _fake_request({}, client_host="192.1.0.88")
        helpers._chat_db_read_grace_until.clear()
        with patch(
            "app.fastapi_routes.domains.conversation.helpers.effective_db_read_token",
            return_value="mytoken",
        ):
            ok, payload = _ensure_chat_db_read_authorized(
                req, message="查询数据库", provided_token="wrong"
            )
        assert ok is False
        assert payload is not None
        assert payload.get("requires_token") is True


# ===========================================================================
# 4. _xcagi_chat_http_exc branches (lines 293-308)
# ===========================================================================


class TestXcagiChatHttpExc:
    def test_timeout_error(self):
        exc = _xcagi_chat_http_exc(TimeoutError("too slow"))
        assert exc.status_code == 504

    def test_httpx_connect_error(self):
        import httpx

        exc = _xcagi_chat_http_exc(httpx.ConnectError("refused"))
        assert exc.status_code == 503

    def test_httpx_http_error(self):
        import httpx

        exc = _xcagi_chat_http_exc(
            httpx.HTTPStatusError("bad", request=MagicMock(), response=MagicMock())
        )
        assert exc.status_code == 502

    def test_authentication_error(self):
        from openai import AuthenticationError

        exc = _xcagi_chat_http_exc(AuthenticationError("bad key", response=MagicMock(), body={}))
        assert exc.status_code == 401

    def test_rate_limit_error(self):
        from openai import RateLimitError

        exc = _xcagi_chat_http_exc(RateLimitError("rate", response=MagicMock(), body={}))
        assert exc.status_code == 429

    def test_runtime_error(self):
        exc = _xcagi_chat_http_exc(RuntimeError("broken"))
        assert exc.status_code == 503

    def test_value_error_balance(self):
        exc = _xcagi_chat_http_exc(ValueError("余额不足，402"))
        assert exc.status_code == 402

    def test_value_error_platform(self):
        exc = _xcagi_chat_http_exc(ValueError("平台错误: something"))
        assert exc.status_code == 502

    def test_generic_exception(self):
        exc = _xcagi_chat_http_exc(Exception("unknown"))
        assert exc.status_code == 500


# ===========================================================================
# 5. _xcagi_compat_reply_payload branches (lines 302-308)
# ===========================================================================


class TestXcagiCompatReplyPayload:
    def test_plain_str_reply(self):
        result = _xcagi_compat_reply_payload("hello world")
        assert result["success"] is True
        assert result["response"] == "hello world"

    def test_dict_reply_with_thinking(self):
        result = _xcagi_compat_reply_payload({"response": "ok", "thinking_steps": "step1\nstep2"})
        assert result["success"] is True
        assert result["data"]["thinking_steps"] == "step1\nstep2"

    def test_dict_reply_with_tool_records_and_errors(self):
        records = [
            {
                "tool_id": "foo",
                "tool_name": "foo",
                "tool_call_id": "c1",
                "params": {"x": 1},
                "output": {
                    "success": False,
                    "error": "E001",
                    "message": "failed",
                    "errors": ["a", "b", "c", "d", "e", "f"],
                },
            }
        ]
        # flatten_tool_result_dict_for_client is a lazy import inside the function;
        # patch it at the helpers module's import point
        with patch(
            "app.fastapi_routes.domains.conversation.helpers.flatten_tool_result_dict_for_client",
            return_value={"foo": "bar"},
            create=True,
        ):
            result = _xcagi_compat_reply_payload({"response": "done", "_tool_records": records})
        assert result["success"] is True

    def test_reply_payload_with_runtime_context_update(self):
        result = _xcagi_compat_reply_payload("hi", runtime_context_update={"key": "val"})
        assert result["data"]["runtime_context"] == {"key": "val"}

    def test_reply_payload_with_kitten_attachments(self):
        result = _xcagi_compat_reply_payload("hi", kitten_attachments={"k": "v", "n": None})
        assert result["data"].get("k") == "v"
        assert "n" not in result["data"]


# ===========================================================================
# 6. _extract_excel_paths_from_message branches (lines 334-335)
# ===========================================================================


class TestExtractExcelPathsFromMessage:
    def test_no_excel_in_message(self):
        assert _extract_excel_paths_from_message("hello world") == []

    def test_single_xlsx_path(self):
        paths = _extract_excel_paths_from_message("请分析 @data/file.xlsx 好吗")
        assert any("file.xlsx" in p for p in paths)

    def test_multiple_xlsx_paths(self):
        paths = _extract_excel_paths_from_message("file1.xlsx 和 file2.xlsm")
        assert len(paths) == 2

    def test_empty_message(self):
        assert _extract_excel_paths_from_message("") == []


# ===========================================================================
# 7. _extract_excel_paths_from_context branches (lines 386-385, 391-394)
# ===========================================================================


class TestExtractExcelPathsFromContext:
    def test_single_excel_file_path(self):
        ctx = {"excel_file_path": "/data/test.xlsx"}
        paths = _extract_excel_paths_from_context(ctx)
        assert "/data/test.xlsx" in paths

    def test_excel_file_paths_list(self):
        ctx = {"excel_file_paths": ["/a.xlsx", "/b.xlsm"]}
        paths = _extract_excel_paths_from_context(ctx)
        assert "/a.xlsx" in paths
        assert "/b.xlsm" in paths

    def test_excel_analysis_nested(self):
        ctx = {
            "excel_analysis": {
                "file_path": "/nested.xlsx",
                "preview_data": {"file_path": "/preview.xlsx"},
            }
        }
        paths = _extract_excel_paths_from_context(ctx)
        assert "/nested.xlsx" in paths
        assert "/preview.xlsx" in paths

    def test_non_xlsx_ignored(self):
        ctx = {"excel_file_path": "/data/notes.txt"}
        paths = _extract_excel_paths_from_context(ctx)
        assert paths == []


# ===========================================================================
# 8. _merge_runtime_context_with_message_paths (lines 501-502, 512-516)
# ===========================================================================


class TestMergeRuntimeContextWithMessagePaths:
    def test_no_paths_returns_empty_list(self):
        ctx, found = _merge_runtime_context_with_message_paths(None, "no excel here")
        assert found == []

    def test_message_path_added_to_context(self):
        ctx, found = _merge_runtime_context_with_message_paths({}, "see report.xlsx please")
        assert any("report.xlsx" in p for p in found)
        assert ctx.get("excel_file_path") is not None

    def test_ctx_path_overlaps_with_message_basename(self):
        # Same basename in context and message: context path should appear first
        ctx_in = {"excel_file_path": "/full/path/report.xlsx"}
        _, found = _merge_runtime_context_with_message_paths(ctx_in, "report.xlsx")
        # found is list of message paths
        assert any("report.xlsx" in p for p in found)


# ===========================================================================
# 9. _ensure_vector_index_if_needed (lines 549-551, 553-557)
# ===========================================================================


class TestEnsureVectorIndexIfNeeded:
    def test_not_vector_request_returns_none(self):
        result = _ensure_vector_index_if_needed("普通消息", {})
        assert result is None

    def test_vector_request_no_file_path_returns_message(self):
        result = _ensure_vector_index_if_needed("向量检索", {})
        assert result is not None
        assert "路径" in result or "Excel" in result or "xlsx" in result.lower()

    def test_vector_request_with_file_path_success(self):
        # resolve_planner_tool_executor() is called with no args and returns an executor.
        # The executor is then called as executor(tool_name, params, workspace_root=root).
        # Patch return_value must itself accept (**kw) since it IS the executor.
        def _fake_executor(*a, **kw):
            return json.dumps({"success": True})

        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=_fake_executor,
        ):
            result = _ensure_vector_index_if_needed("向量索引", {"excel_file_path": "/x.xlsx"})
        assert result is None

    def test_vector_request_with_file_path_error_result(self):
        def _fake_executor(*a, **kw):
            return json.dumps({"error": "E", "message": "fail"})

        with patch(
            "app.mod_sdk.planner_tools.resolve_planner_tool_executor",
            return_value=_fake_executor,
        ):
            result = _ensure_vector_index_if_needed("向量索引", {"excel_file_path": "/x.xlsx"})
        assert result is not None
        assert "fail" in result


# ===========================================================================
# 10. _thinking_steps_from_planner_stream_text / strip_planner_stream_markers
# ===========================================================================


class TestThinkingSteps:
    def test_empty_text_returns_none(self):
        assert _thinking_steps_from_planner_stream_text("") is None

    def test_whitespace_returns_none(self):
        assert _thinking_steps_from_planner_stream_text("   ") is None

    def test_tool_call_markers_extracted(self):
        text = "[正在调用工具:foo_tool] result [工具已返回成功]"
        steps = _thinking_steps_from_planner_stream_text(text)
        assert steps is not None
        assert "正在调用工具" in steps

    def test_auth_markers_extracted(self):
        text = "[需要授权:db_token] please provide"
        steps = _thinking_steps_from_planner_stream_text(text)
        assert steps is not None
        assert "需要授权" in steps

    def test_no_markers_returns_none(self):
        steps = _thinking_steps_from_planner_stream_text("hello world no markers")
        assert steps is None

    def test_strip_markers_cleans_text(self):
        text = "[正在调用工具:bar] the result here [工具已返回ok]"
        cleaned, thinking = strip_planner_stream_markers(text)
        assert "正在调用工具" not in cleaned
        assert thinking is not None

    def test_strip_markers_deduplicates(self):
        marker = "[正在调用工具:baz]"
        text = f"{marker} text {marker}"
        _, thinking = strip_planner_stream_markers(text)
        assert thinking is not None
        # deduplicated → only one copy
        assert thinking.count("baz") == 1


# ===========================================================================
# 11. Timeout helpers branches (lines 677-704)
# ===========================================================================


class TestTimeoutHelpers:
    def test_default_timeout(self):
        with patch.dict(os.environ, {"XCAGI_CHAT_TIMEOUT_SEC": "120"}):
            assert _xcagi_chat_timeout_seconds() == 120.0

    def test_invalid_timeout_fallback(self):
        with patch.dict(os.environ, {"XCAGI_CHAT_TIMEOUT_SEC": "bad"}):
            assert _xcagi_chat_timeout_seconds() == 120.0

    def test_clamp_min(self):
        with patch.dict(os.environ, {"XCAGI_CHAT_TIMEOUT_SEC": "1"}):
            assert _xcagi_chat_timeout_seconds() == 5.0

    def test_clamp_max(self):
        with patch.dict(os.environ, {"XCAGI_CHAT_TIMEOUT_SEC": "9999"}):
            assert _xcagi_chat_timeout_seconds() == 600.0

    def test_first_token_timeout_valid(self):
        with patch.dict(os.environ, {"XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC": "30"}):
            assert _xcagi_stream_first_token_timeout_seconds() == 30.0

    def test_first_token_timeout_invalid(self):
        with patch.dict(os.environ, {"XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC": "x"}):
            assert _xcagi_stream_first_token_timeout_seconds() == 20.0
