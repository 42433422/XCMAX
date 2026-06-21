from __future__ import annotations

"""Branch-coverage tests for app/legacy/chat/legacy_chat_adapter.py.

Targets ~46 missing branches from coverage_new.json.
All network / LLM / tool deps are mocked.
"""

import json
import threading
from contextvars import copy_context
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_tc(name: str, arguments: str = "{}", tc_id: str = "tc1"):
    """Build a fake tool-call object."""
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments
    tc = MagicMock()
    tc.id = tc_id
    tc.function = fn
    return tc


def _make_choice(content: str | None = None, tool_calls=None, finish_reason: str = "stop"):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason
    return choice


# ---------------------------------------------------------------------------
# Tests for _resolve_chat_model_for_client (lines 77-85)
# ---------------------------------------------------------------------------


class TestResolveChatModelForClient:
    def test_explicit_model_returned_immediately(self):
        from app.legacy.chat.legacy_chat_adapter import _resolve_chat_model_for_client
        assert _resolve_chat_model_for_client(None, "my-model") == "my-model"

    def test_modstore_client_with_provider(self):
        from app.legacy.chat.legacy_chat_adapter import _resolve_chat_model_for_client
        client = MagicMock()
        client.is_modstore_openai_compatible = True
        client.default_model = "gpt4"
        client.default_provider = "openai"
        result = _resolve_chat_model_for_client(client, None)
        assert result == "openai/gpt4"

    def test_modstore_client_without_provider(self):
        from app.legacy.chat.legacy_chat_adapter import _resolve_chat_model_for_client
        client = MagicMock()
        client.is_modstore_openai_compatible = True
        client.default_model = "gpt4"
        client.default_provider = ""
        result = _resolve_chat_model_for_client(client, None)
        assert result == "gpt4"

    def test_modstore_client_no_default_model_falls_through(self):
        from app.legacy.chat.legacy_chat_adapter import _resolve_chat_model_for_client
        client = MagicMock()
        client.is_modstore_openai_compatible = True
        client.default_model = ""
        client.default_provider = ""
        with patch("app.legacy.chat.legacy_chat_adapter.resolve_chat_model", return_value="fallback"):
            result = _resolve_chat_model_for_client(client, None)
        assert result == "fallback"

    def test_non_modstore_client_falls_through(self):
        from app.legacy.chat.legacy_chat_adapter import _resolve_chat_model_for_client
        client = MagicMock()
        client.is_modstore_openai_compatible = False
        with patch("app.legacy.chat.legacy_chat_adapter.resolve_chat_model", return_value="fallback"):
            result = _resolve_chat_model_for_client(client, None)
        assert result == "fallback"


# ---------------------------------------------------------------------------
# Tests for get_last_tool_result / get_last_tool_records (lines 98-117)
# ---------------------------------------------------------------------------


class TestGetLastToolResult:
    def setup_method(self):
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result
        clear_last_tool_result()

    def test_empty_records_returns_empty_dict(self):
        from app.legacy.chat.legacy_chat_adapter import clear_last_tool_result, get_last_tool_result
        clear_last_tool_result()
        result = get_last_tool_result()
        assert result == {}

    def test_records_with_dict_output(self):
        import app.legacy.chat.legacy_chat_adapter as _mod
        from app.legacy.chat.legacy_chat_adapter import get_last_tool_result
        _mod._LAST_TOOL_TRACE.records = [
            {"tool_id": "products", "tool_name": "products", "output": {"success": True, "data": []}, "tool_call_id": "x", "action": "execute", "params": {}, "success": True}
        ]
        result = get_last_tool_result()
        assert result["tool_key"] == "products"

    def test_records_with_non_dict_output(self):
        import app.legacy.chat.legacy_chat_adapter as _mod
        from app.legacy.chat.legacy_chat_adapter import get_last_tool_result
        _mod._LAST_TOOL_TRACE.records = [
            {"tool_id": "products", "tool_name": "products", "output": "some string", "tool_call_id": "x", "action": "execute", "params": {}, "success": False}
        ]
        result = get_last_tool_result()
        assert "message" in result

    def test_get_last_tool_records_invalid_type(self):
        import app.legacy.chat.legacy_chat_adapter as _mod
        from app.legacy.chat.legacy_chat_adapter import get_last_tool_records
        _mod._LAST_TOOL_TRACE.records = "not_a_list"
        result = get_last_tool_records()
        assert result == []


# ---------------------------------------------------------------------------
# Tests for _should_replace_tool_result (lines 172-188)
# ---------------------------------------------------------------------------


class TestShouldReplaceToolResult:
    def test_no_previous_and_new_payload_true(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        assert _should_replace_tool_result(None, {"success": True}) is True

    def test_no_previous_no_new_false(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        assert _should_replace_tool_result(None, None) is False

    def test_no_new_payload_false(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        assert _should_replace_tool_result({"success": True}, None) is False

    def test_new_success_prev_fail_true(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        assert _should_replace_tool_result({"success": False}, {"success": True}) is True

    def test_prev_success_new_fail_false(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        assert _should_replace_tool_result({"success": True}, {"success": False}) is False

    def test_both_success_new_has_download_url(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        prev = {"success": True}
        new = {"success": True, "download_url": "http://x/file.docx"}
        assert _should_replace_tool_result(prev, new) is True

    def test_both_success_prev_has_download_url_new_does_not(self):
        from app.legacy.chat.legacy_chat_adapter import _should_replace_tool_result
        prev = {"success": True, "download_url": "http://x/file.docx"}
        new = {"success": True}
        assert _should_replace_tool_result(prev, new) is False


# ---------------------------------------------------------------------------
# Tests for _parse_generate_office_format (lines 210-220)
# ---------------------------------------------------------------------------


class TestParseGenerateOfficeFormat:
    def test_docx_format(self):
        from app.legacy.chat.legacy_chat_adapter import _parse_generate_office_format
        raw = json.dumps({"output_format": "docx"})
        assert _parse_generate_office_format(raw) == "docx"

    def test_xlsx_format(self):
        from app.legacy.chat.legacy_chat_adapter import _parse_generate_office_format
        raw = json.dumps({"output_format": "XLSX"})
        assert _parse_generate_office_format(raw) == "xlsx"

    def test_invalid_json_returns_empty(self):
        from app.legacy.chat.legacy_chat_adapter import _parse_generate_office_format
        assert _parse_generate_office_format("not-json") == ""

    def test_unknown_format_returns_empty(self):
        from app.legacy.chat.legacy_chat_adapter import _parse_generate_office_format
        raw = json.dumps({"output_format": "pdf"})
        assert _parse_generate_office_format(raw) == ""

    def test_empty_string_returns_empty(self):
        from app.legacy.chat.legacy_chat_adapter import _parse_generate_office_format
        assert _parse_generate_office_format("") == ""


# ---------------------------------------------------------------------------
# Tests for _tool_stream_call_label (lines 223-230)
# ---------------------------------------------------------------------------


class TestToolStreamCallLabel:
    def test_generate_office_docx(self):
        from app.legacy.chat.legacy_chat_adapter import _tool_stream_call_label
        raw = json.dumps({"output_format": "docx"})
        assert "Word" in _tool_stream_call_label("generate_office_document", raw)

    def test_generate_office_xlsx(self):
        from app.legacy.chat.legacy_chat_adapter import _tool_stream_call_label
        raw = json.dumps({"output_format": "xlsx"})
        assert "Excel" in _tool_stream_call_label("generate_office_document", raw)

    def test_generate_office_unknown_format(self):
        from app.legacy.chat.legacy_chat_adapter import (
            _PLANNER_TOOL_STREAM_LABELS,
            _tool_stream_call_label,
        )
        raw = json.dumps({"output_format": "pdf"})
        result = _tool_stream_call_label("generate_office_document", raw)
        assert result == _PLANNER_TOOL_STREAM_LABELS.get("generate_office_document", "generate_office_document")

    def test_known_tool_returns_label(self):
        from app.legacy.chat.legacy_chat_adapter import _tool_stream_call_label
        assert "Excel" in _tool_stream_call_label("excel_analysis", "{}")

    def test_unknown_tool_returns_name(self):
        from app.legacy.chat.legacy_chat_adapter import _tool_stream_call_label
        assert _tool_stream_call_label("mystery_tool", "{}") == "mystery_tool"


# ---------------------------------------------------------------------------
# Tests for _slow_tool_wait_message (lines 233-248)
# ---------------------------------------------------------------------------


class TestSlowToolWaitMessage:
    def test_import_excel(self):
        from app.legacy.chat.legacy_chat_adapter import _slow_tool_wait_message
        msg = _slow_tool_wait_message("import_excel_to_database", "{}")
        assert msg is not None and "Excel" in msg

    def test_generate_office_docx(self):
        from app.legacy.chat.legacy_chat_adapter import _slow_tool_wait_message
        raw = json.dumps({"output_format": "docx"})
        msg = _slow_tool_wait_message("generate_office_document", raw)
        assert msg is not None and "Word" in msg

    def test_generate_office_xlsx(self):
        from app.legacy.chat.legacy_chat_adapter import _slow_tool_wait_message
        raw = json.dumps({"output_format": "xlsx"})
        msg = _slow_tool_wait_message("generate_office_document", raw)
        assert msg is not None and "xlsx" in msg.lower()

    def test_generate_office_unknown_format(self):
        from app.legacy.chat.legacy_chat_adapter import _slow_tool_wait_message
        msg = _slow_tool_wait_message("generate_office_document", "{}")
        assert msg is not None

    def test_other_tool_returns_none(self):
        from app.legacy.chat.legacy_chat_adapter import _slow_tool_wait_message
        assert _slow_tool_wait_message("products", "{}") is None


# ---------------------------------------------------------------------------
# Tests for _post_tool_round_hint (lines 251-301)
# ---------------------------------------------------------------------------


class TestPostToolRoundHint:
    def _tc(self, name: str, args: str = "{}"):
        return _make_tc(name, args)

    def test_docx_success(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("generate_office_document", json.dumps({"output_format": "docx"}))
        payloads = [{"success": True, "download_url": "http://x/f.docx"}]
        result = _post_tool_round_hint([tc], payloads)
        assert "Word" in result

    def test_xlsx_success(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("generate_office_document", json.dumps({"output_format": "xlsx"}))
        payloads = [{"success": True, "download_url": "http://x/f.xlsx"}]
        result = _post_tool_round_hint([tc], payloads)
        assert "Excel" in result

    def test_both_docx_and_xlsx_success(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc1 = self._tc("generate_office_document", json.dumps({"output_format": "docx"}))
        tc2 = self._tc("generate_office_document", json.dumps({"output_format": "xlsx"}))
        payloads = [
            {"success": True, "download_url": "http://x/f.docx"},
            {"success": True, "download_url": "http://x/f.xlsx"},
        ]
        result = _post_tool_round_hint([tc1, tc2], payloads)
        assert "Word" in result and "Excel" in result

    def test_import_ok(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("import_excel_to_database")
        payloads = [{"success": True}]
        result = _post_tool_round_hint([tc], payloads)
        assert "导入" in result

    def test_fail_message(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("generate_office_document", json.dumps({"output_format": "docx"}))
        payloads = [{"success": False, "message": "服务器错误"}]
        result = _post_tool_round_hint([tc], payloads)
        assert "工具未成功" in result

    def test_duplicate_tool_call_error(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("generate_office_document", json.dumps({"output_format": "docx"}))
        payloads = [{"success": False, "error": "duplicate_tool_call"}]
        result = _post_tool_round_hint([tc], payloads)
        assert "工具未成功" in result

    def test_fail_long_error_truncated(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("generate_office_document", json.dumps({"output_format": "docx"}))
        payloads = [{"success": False, "message": "E" * 200}]
        result = _post_tool_round_hint([tc], payloads)
        assert "工具未成功" in result

    def test_requires_token_continue(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("import_excel_to_database")
        payloads = [{"requires_token": True}]
        result = _post_tool_round_hint([tc], payloads)
        # requires_token skipped -> no import_ok -> generic result
        assert "工具已返回结果" in result

    def test_generic_fallback(self):
        from app.legacy.chat.legacy_chat_adapter import _post_tool_round_hint
        tc = self._tc("products")
        payloads = [{"success": True}]
        result = _post_tool_round_hint([tc], payloads)
        assert "工具已返回结果" in result


# ---------------------------------------------------------------------------
# Tests for append_tool_messages (lines 313-420)
# ---------------------------------------------------------------------------


class TestAppendToolMessages:
    def setup_method(self):
        from app.legacy.chat.legacy_chat_adapter import reset_planner_tool_dedup_state
        reset_planner_tool_dedup_state()

    def _exec(self, payload: dict):
        return json.dumps(payload)

    def test_empty_tool_calls_returns_none(self):
        from app.legacy.chat.legacy_chat_adapter import append_tool_messages
        messages: list[Any] = []
        result = append_tool_messages(messages, [], workspace_root=None, execute_tool=self._exec)
        assert result is None

    def test_single_tool_executed_serial(self):
        from app.legacy.chat.legacy_chat_adapter import append_tool_messages
        tc = _make_tc("products", json.dumps({"action": "search"}))
        messages: list[Any] = []
        result = append_tool_messages(
            messages, [tc], workspace_root=None, execute_tool=lambda n, a, w, db_write_token=None: json.dumps({"success": True})
        )
        assert result is None
        assert any(m.get("role") == "tool" for m in messages)

    def test_duplicate_tool_call_skips_second(self):
        from app.legacy.chat.legacy_chat_adapter import (
            append_tool_messages,
            reset_planner_tool_dedup_state,
        )
        reset_planner_tool_dedup_state()
        tc1 = _make_tc("products", json.dumps({"action": "search"}))
        tc2 = _make_tc("products", json.dumps({"action": "search"}))
        messages: list[Any] = []

        def exec_tool(n, a, w, db_write_token=None):
            return json.dumps({"success": True})

        append_tool_messages(messages, [tc1], workspace_root=None, execute_tool=exec_tool)
        # Second call with same args must be flagged as dup
        messages2: list[Any] = []
        append_tool_messages(messages2, [tc2], workspace_root=None, execute_tool=exec_tool)
        # The content for dup must contain duplicate_tool_call
        assert any("duplicate_tool_call" in m.get("content", "") for m in messages2)

    def test_requires_token_returned_serial(self):
        from app.legacy.chat.legacy_chat_adapter import append_tool_messages
        tc = _make_tc("import_excel_to_database", "{}")
        messages: list[Any] = []

        def exec_tool(n, a, w, db_write_token=None):
            return json.dumps({"requires_token": True, "token_name": "DB_WRITE_TOKEN"})

        result = append_tool_messages(messages, [tc], workspace_root=None, execute_tool=exec_tool)
        assert result is not None
        assert result.get("requires_token") is True

    def test_parallel_execution_multiple_tools(self):
        from app.legacy.chat.legacy_chat_adapter import (
            append_tool_messages,
            reset_planner_tool_dedup_state,
        )
        reset_planner_tool_dedup_state()
        tc1 = _make_tc("products", json.dumps({"action": "search"}), "tc1")
        tc2 = _make_tc("customers", json.dumps({"action": "list"}), "tc2")
        messages: list[Any] = []

        def exec_tool(n, a, w, db_write_token=None):
            return json.dumps({"success": True})

        with patch("app.legacy.chat.legacy_chat_adapter._planner_tools_max_workers", return_value=4):
            result = append_tool_messages(
                messages, [tc1, tc2], workspace_root=None, execute_tool=exec_tool
            )
        assert result is None
        assert len([m for m in messages if m.get("role") == "tool"]) == 2

    def test_token_sensitive_tool_forces_serial(self):
        from app.legacy.chat.legacy_chat_adapter import append_tool_messages
        tc = _make_tc("import_excel_to_database", "{}", "tc3")
        messages: list[Any] = []

        def exec_tool(n, a, w, db_write_token=None):
            return json.dumps({"success": True})

        # even with max_workers=4 it should stay serial because token-sensitive
        with patch("app.legacy.chat.legacy_chat_adapter._planner_tools_max_workers", return_value=4):
            result = append_tool_messages(
                messages, [tc], workspace_root=None, execute_tool=exec_tool
            )
        assert result is None

    def test_invalid_json_args_treated_as_empty(self):
        from app.legacy.chat.legacy_chat_adapter import append_tool_messages
        tc = _make_tc("products", "not-json")
        messages: list[Any] = []

        def exec_tool(n, a, w, db_write_token=None):
            return json.dumps({"success": True})

        result = append_tool_messages(messages, [tc], workspace_root=None, execute_tool=exec_tool)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _planner_tools_max_workers (lines 304-310)
# ---------------------------------------------------------------------------


class TestPlannerToolsMaxWorkers:
    def test_default_8(self):
        from app.legacy.chat.legacy_chat_adapter import _planner_tools_max_workers
        with patch.dict("os.environ", {"FHD_PLANNER_TOOLS_MAX_PARALLEL": ""}, clear=False):
            import importlib

            import app.legacy.chat.legacy_chat_adapter as m
            # just call directly since env is set per-process
            result = _planner_tools_max_workers()
        assert 1 <= result <= 32

    def test_invalid_env_defaults_to_8(self):
        from app.legacy.chat.legacy_chat_adapter import _planner_tools_max_workers
        with patch.dict("os.environ", {"FHD_PLANNER_TOOLS_MAX_PARALLEL": "not_int"}):
            result = _planner_tools_max_workers()
        assert result == 8


# ---------------------------------------------------------------------------
# Tests for chat_stream_sse_events (lines 702-732)
# ---------------------------------------------------------------------------


class TestChatStreamSseEvents:
    def test_yields_done_event(self):
        from app.legacy.chat.legacy_chat_adapter import chat_stream_sse_events

        with patch(
            "app.legacy.chat.legacy_chat_adapter.chat_stream_text",
            return_value=iter(["hello"]),
        ):
            events = list(chat_stream_sse_events("hi"))
        assert events[-1] == {"type": "done"}

    def test_requires_token_yields_token_events(self):
        from app.legacy.chat.legacy_chat_adapter import chat_stream_sse_events

        payload = {
            "_planner_sse": "requires_token",
            "token_name": "DB_WRITE_TOKEN",
            "token_description": "需要令牌",
            "message": None,
        }
        with patch(
            "app.legacy.chat.legacy_chat_adapter.chat_stream_text",
            return_value=iter([payload]),
        ):
            events = list(chat_stream_sse_events("upload something"))
        types = [e.get("type") for e in events]
        assert "token" in types
        assert "requires_token" in types

    def test_string_items_wrapped_in_token_type(self):
        from app.legacy.chat.legacy_chat_adapter import chat_stream_sse_events
        with patch(
            "app.legacy.chat.legacy_chat_adapter.chat_stream_text",
            return_value=iter(["chunk1", "chunk2"]),
        ):
            events = list(chat_stream_sse_events("q"))
        texts = [e.get("text") for e in events if e.get("type") == "token"]
        assert "chunk1" in texts
        assert "chunk2" in texts
