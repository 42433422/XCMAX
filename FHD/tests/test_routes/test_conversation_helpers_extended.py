"""Comprehensive tests for conversation/helpers — covering _ensure_vector_index_if_needed,
Conversation reply and asynchronous stream helpers
with tool results, _chat_db_read_grace_seconds_left, _touch_chat_db_read_grace, and other
uncovered branches.

Extends the existing test file with additional coverage for uncovered lines.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.fastapi_routes.domains.conversation import helpers


def _patch_conversation(name, *args, **kwargs):
    """Patch the conversation facade without repeating its qualified module path."""
    return patch(f"app.fastapi_routes.domains.conversation.helpers.{name}", *args, **kwargs)


@contextmanager
def _planner_context(*, vector_error=None):
    """Use an empty, authorized runtime while leaving stream behavior to each test."""
    with (
        _patch_conversation("effective_db_read_token", return_value=""),
        _patch_conversation("_merge_runtime_context_with_message_paths", return_value=({}, [])),
        _patch_conversation("runtime_context_with_tier", return_value={}),
        _patch_conversation("planner_workflow_interrupt_reply", return_value=None),
        _patch_conversation("_ensure_vector_index_if_needed", return_value=vector_error),
    ):
        yield


# ---------------------------------------------------------------------------
# _chat_db_read_grace_seconds_left / _touch_chat_db_read_grace
# ---------------------------------------------------------------------------


class TestChatDbReadGrace:
    """Tests for grace period management functions."""

    def test_touch_then_check_grace(self):
        """After touching grace, seconds_left should be positive."""
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": "10.0.0.1"}
        req.client = None

        # Touch grace
        seconds = helpers._touch_chat_db_read_grace(req)
        assert seconds == 5 * 60  # _CHAT_DB_READ_GRACE_SEC

        # Check grace
        left = helpers._chat_db_read_grace_seconds_left(req)
        assert left > 0
        assert left <= 5 * 60

    def test_no_grace_returns_zero(self):
        """Without touching grace, seconds_left should be 0."""
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": "99.99.99.99_unique_for_test"}
        req.client = None

        left = helpers._chat_db_read_grace_seconds_left(req)
        assert left == 0

    def test_grace_expires(self):
        """Grace should expire after _CHAT_DB_READ_GRACE_SEC."""
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": "10.0.0.2"}
        req.client = None

        # Manually set expired grace
        subject = helpers._chat_request_subject(req)
        with helpers._chat_db_read_grace_lock:
            helpers._chat_db_read_grace_until[subject] = time.time() - 1  # expired

        left = helpers._chat_db_read_grace_seconds_left(req)
        assert left == 0

    def test_touch_grace_cleans_up_expired(self):
        """Checking expired grace should clean up the entry."""
        req = MagicMock(spec=Request)
        req.headers = {"x-forwarded-for": "10.0.0.3"}
        req.client = None

        subject = helpers._chat_request_subject(req)
        with helpers._chat_db_read_grace_lock:
            helpers._chat_db_read_grace_until[subject] = time.time() - 100

        left = helpers._chat_db_read_grace_seconds_left(req)
        assert left == 0
        # Entry should be cleaned up
        with helpers._chat_db_read_grace_lock:
            assert subject not in helpers._chat_db_read_grace_until


# ---------------------------------------------------------------------------
# _ensure_vector_index_if_needed
# ---------------------------------------------------------------------------


class TestEnsureVectorIndexIfNeeded:
    """Tests for _ensure_vector_index_if_needed function."""

    def test_non_vector_request_returns_none(self):
        """Non-vector requests should return None."""
        result = helpers._ensure_vector_index_if_needed("你好", {})
        assert result is None

    def test_vector_request_no_file_path(self):
        """Vector request without file path should return error message."""
        result = helpers._ensure_vector_index_if_needed("建立向量索引", {})
        assert result is not None
        assert "向量" in result or "Excel" in result

    def test_vector_request_with_file_path_success(self):
        """Vector request with file path and successful indexing should return None."""
        runtime_context = {"excel_file_path": "/data/test.xlsx"}
        mock_result = {"success": True, "index_size": 100}

        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolve:
            mock_executor = MagicMock(return_value=json.dumps(mock_result))
            mock_resolve.return_value = mock_executor

            result = helpers._ensure_vector_index_if_needed("建立向量索引", runtime_context)
            assert result is None

    def test_vector_request_with_file_path_error_result(self):
        """Vector request with file path but indexing error should return error message."""
        runtime_context = {"excel_file_path": "/data/test.xlsx"}
        mock_result = {"error": "file not found", "message": "文件不存在"}

        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolve:
            mock_executor = MagicMock(return_value=json.dumps(mock_result))
            mock_resolve.return_value = mock_executor

            result = helpers._ensure_vector_index_if_needed("建立向量索引", runtime_context)
            assert result is not None
            assert "文件不存在" in result or "失败" in result

    def test_vector_request_with_file_path_exception(self):
        """Vector request with file path but exception should return error message."""
        runtime_context = {"excel_file_path": "/data/test.xlsx"}

        with patch("app.mod_sdk.planner_tools.resolve_planner_tool_executor") as mock_resolve:
            mock_resolve.side_effect = OSError("connection failed")

            result = helpers._ensure_vector_index_if_needed("建立向量索引", runtime_context)
            assert result is not None
            assert "失败" in result

    def test_vector_request_embedding_keyword(self):
        """Request with 'embedding' keyword should trigger vector check."""
        result = helpers._ensure_vector_index_if_needed("embedding search", {})
        assert result is not None

    def test_vector_request_semantic_search_keyword(self):
        """Request with 'semantic search' keyword should trigger vector check."""
        result = helpers._ensure_vector_index_if_needed("semantic search", {})
        assert result is not None


# ---------------------------------------------------------------------------
# _xcagi_compat_reply_payload — tool result integration
# ---------------------------------------------------------------------------


class TestXcagiCompatReplyPayloadWithToolResults:
    """Tests for _xcagi_compat_reply_payload.

    Tool results are supplied explicitly by the current reply,
    so the tool result branch is always skipped via RECOVERABLE_ERRORS catch.
    We test the actual behavior paths that exist.
    """

    def test_string_reply_no_tool_data(self):
        """String reply without tool data should return basic payload."""
        result = helpers._xcagi_compat_reply_payload("操作完成")
        assert result["success"] is True
        assert result["response"] == "操作完成"
        assert result["data"]["text"] == "操作完成"

    def test_dict_reply_with_response_key(self):
        """Dict reply with 'response' key should use it."""
        result = helpers._xcagi_compat_reply_payload({"response": "done"})
        assert result["response"] == "done"

    def test_dict_reply_with_text_key_fallback(self):
        """Dict reply with 'text' key should use it as response."""
        result = helpers._xcagi_compat_reply_payload({"text": "hello world"})
        assert result["response"] == "hello world"

    def test_dict_reply_with_thinking_steps(self):
        """Dict reply with thinking_steps should include them in data."""
        result = helpers._xcagi_compat_reply_payload(
            {"response": "done", "thinking_steps": "step1\nstep2"}
        )
        assert result["data"]["thinking_steps"] == "step1\nstep2"

    def test_dict_reply_none_response(self):
        """Dict reply with None response/text should return empty string."""
        result = helpers._xcagi_compat_reply_payload({"response": None})
        assert result["response"] == ""

    def test_dict_reply_with_runtime_context_update(self):
        """Dict reply with runtime_context_update should include it in data."""
        ctx_update = {"cleared": True}
        result = helpers._xcagi_compat_reply_payload("done", runtime_context_update=ctx_update)
        assert result["data"]["runtime_context"] == ctx_update

    def test_dict_reply_with_kitten_attachments(self):
        """Dict reply with kitten_attachments should spread items into data."""
        attachments = {"files": ["a.xlsx"]}
        result = helpers._xcagi_compat_reply_payload("done", kitten_attachments=attachments)
        assert result["data"]["files"] == ["a.xlsx"]

    def test_empty_string_reply(self):
        """Empty string reply should return empty response."""
        result = helpers._xcagi_compat_reply_payload("")
        assert result["response"] == ""

    def test_tool_result_import_fails_gracefully(self):
        """A reply without tool records still returns a valid payload."""
        result = helpers._xcagi_compat_reply_payload("完成")
        assert result["success"] is True
        assert result["response"] == "完成"
        # No tool data since the import fails
        assert "工具反馈" not in result["response"]


# ---------------------------------------------------------------------------
# _xcagi_chat_http_exc — additional edge cases
# ---------------------------------------------------------------------------


class TestXcagiChatHttpExcEdgeCases:
    """Additional edge cases for _xcagi_chat_http_exc."""

    def test_timeout_with_custom_message(self):
        """TimeoutError with custom message should use it."""
        exc = helpers._xcagi_chat_http_exc(TimeoutError("custom timeout msg"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 504
        assert "custom timeout msg" in exc.detail

    def test_timeout_with_empty_message(self):
        """TimeoutError with empty message should use default."""
        exc = helpers._xcagi_chat_http_exc(TimeoutError(""))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 504
        assert "超时" in exc.detail

    def test_value_error_with_402_in_message(self):
        """ValueError with '402' should map to 402."""
        exc = helpers._xcagi_chat_http_exc(ValueError("API returned 402"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 402

    def test_value_error_generic(self):
        """Generic ValueError should map to 500."""
        exc = helpers._xcagi_chat_http_exc(ValueError("some value error"))
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 500

    def test_httpx_connect_error(self):
        """httpx.ConnectError should map to 503."""
        try:
            import httpx

            exc = helpers._xcagi_chat_http_exc(httpx.ConnectError("connection refused"))
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 503
        except ImportError:
            pytest.skip("httpx not installed")

    def test_httpx_generic_error(self):
        """httpx.HTTPError should map to 502."""
        try:
            import httpx

            exc = helpers._xcagi_chat_http_exc(httpx.HTTPError("http error"))
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 502
        except ImportError:
            pytest.skip("httpx not installed")


# ---------------------------------------------------------------------------
# _xcagi_planner_stream_bytes_async
# ---------------------------------------------------------------------------


class TestXcagiPlannerStreamBytesAsync:
    """Tests for _xcagi_planner_stream_bytes_async."""

    @pytest.mark.asyncio
    async def test_async_yields_chunks(self):
        """Async wrapper should yield chunks from sync generator."""
        body = helpers.XcagiCompatChatBody(message="hello")

        with _patch_conversation(
            "_xcagi_planner_stream_bytes",
            return_value=iter([b"chunk1", b"chunk2"]),
        ):
            chunks = []
            async for chunk in helpers._xcagi_planner_stream_bytes_async(
                MagicMock(spec=Request), body, ai_tier="default"
            ):
                chunks.append(chunk)
            assert len(chunks) == 2
            assert chunks[0] == b"chunk1"
            assert chunks[1] == b"chunk2"


# ---------------------------------------------------------------------------
# XcagiCompatChatBody — additional edge cases
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBodyEdgeCases:
    """Additional edge cases for XcagiCompatChatBody."""

    def test_alias_text(self):
        body = helpers.XcagiCompatChatBody(text="hello")
        assert body.message == "hello"

    def test_alias_system_prompt(self):
        body = helpers.XcagiCompatChatBody(message="m", instructions="be helpful")
        assert body.system_prompt == "be helpful"

    def test_alias_system(self):
        body = helpers.XcagiCompatChatBody(message="m", system="system prompt")
        assert body.system_prompt == "system prompt"

    def test_alias_mode(self):
        body = helpers.XcagiCompatChatBody(message="m", llm_mode="online")
        assert body.mode == "online"

    def test_db_tokens_default_none(self):
        body = helpers.XcagiCompatChatBody(message="m")
        assert body.db_read_token is None
        assert body.db_write_token is None


# ---------------------------------------------------------------------------
# XcagiCompatChatBatchBody — additional edge cases
# ---------------------------------------------------------------------------


class TestXcagiCompatChatBatchBodyEdgeCases:
    """Additional edge cases for XcagiCompatChatBatchBody."""

    def test_default_messages(self):
        body = helpers.XcagiCompatChatBatchBody()
        assert body.messages == []

    def test_user_id_and_source(self):
        body = helpers.XcagiCompatChatBatchBody(messages=["a"], user_id="user1", source="test")
        assert body.user_id == "user1"
        assert body.source == "test"

    def test_context_alias_neuro_ddd_context(self):
        body = helpers.XcagiCompatChatBatchBody(messages=["a"], neuro_ddd_context={"k": "v"})
        assert body.context == {"k": "v"}


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_message — additional edge cases
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromMessageEdgeCases:
    """Additional edge cases for _extract_excel_paths_from_message."""

    def test_xls_extension(self):
        paths = helpers._extract_excel_paths_from_message("打开 file.xls 文件")
        assert len(paths) == 1

    def test_path_with_at_sign(self):
        paths = helpers._extract_excel_paths_from_message("@data/test.xlsx")
        assert len(paths) == 1

    def test_none_message(self):
        paths = helpers._extract_excel_paths_from_message(None)
        assert paths == []


# ---------------------------------------------------------------------------
# _extract_excel_paths_from_context — additional edge cases
# ---------------------------------------------------------------------------


class TestExtractExcelPathsFromContextEdgeCases:
    """Additional edge cases for _extract_excel_paths_from_context."""

    def test_non_string_excel_file_path(self):
        """Non-string excel_file_path should be skipped."""
        ctx = {"excel_file_path": 123}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert paths == []

    def test_non_list_excel_file_paths(self):
        """Non-list excel_file_paths should be skipped."""
        ctx = {"excel_file_paths": "not_a_list"}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert paths == []

    def test_excel_analysis_non_dict(self):
        """Non-dict excel_analysis should be skipped."""
        ctx = {"excel_analysis": "not_a_dict"}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert paths == []

    def test_excel_analysis_preview_non_dict(self):
        """Non-dict preview_data should be skipped."""
        ctx = {"excel_analysis": {"preview_data": "not_a_dict"}}
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert paths == []

    def test_dedup_paths(self):
        """Duplicate paths should be deduplicated."""
        ctx = {
            "excel_file_path": "test.xlsx",
            "excel_file_paths": ["test.xlsx"],
        }
        paths = helpers._extract_excel_paths_from_context(ctx)
        assert len(paths) == 1


# ---------------------------------------------------------------------------
# _merge_runtime_context_with_message_paths — additional edge cases
# ---------------------------------------------------------------------------


class TestMergeRuntimeContextWithMessagePathsEdgeCases:
    """Additional edge cases for _merge_runtime_context_with_message_paths."""

    def test_none_runtime_context(self):
        """None runtime_context should be treated as empty dict."""
        ctx, found = helpers._merge_runtime_context_with_message_paths(None, "test.xlsx")
        assert "test.xlsx" in found[0]

    def test_both_message_and_context_paths(self):
        """When both message and context have paths, should merge with dedup."""
        ctx, found = helpers._merge_runtime_context_with_message_paths(
            {"excel_file_path": "/full/path/test.xlsx"},
            "分析 test.xlsx",
        )
        all_paths = ctx.get("excel_file_paths", [])
        assert len(all_paths) >= 1

    def test_context_path_not_in_message(self):
        """Context path not matching message basename should be appended."""
        ctx, found = helpers._merge_runtime_context_with_message_paths(
            {"excel_file_path": "other.xlsx"},
            "分析 test.xlsx",
        )
        all_paths = ctx.get("excel_file_paths", [])
        assert len(all_paths) == 2
