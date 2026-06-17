"""Tests for app.application.workflow.legacy_chat_adapter."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.legacy_chat_adapter import (
    _parse_generate_office_format,
    _planner_tools_max_workers,
    _post_tool_round_hint,
    _resolve_chat_model_for_client,
    _slow_tool_wait_message,
    _tool_key,
    _tool_stream_call_label,
    append_tool_messages,
    chat,
    chat_stream_sse_events,
    chat_stream_text,
    reset_planner_tool_dedup_state,
)


# ---------------------------------------------------------------------------
# Helper: lightweight tool-call stub
# ---------------------------------------------------------------------------
class _Fn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _Tc:
    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.function = _Fn(name, arguments)


# ---------------------------------------------------------------------------
# _parse_generate_office_format
# ---------------------------------------------------------------------------
class TestParseGenerateOfficeFormat:
    def test_docx(self):
        assert _parse_generate_office_format('{"output_format":"docx"}') == "docx"

    def test_xlsx(self):
        assert _parse_generate_office_format('{"output_format":"xlsx"}') == "xlsx"

    def test_uppercase_format(self):
        assert _parse_generate_office_format('{"output_format":"DOCX"}') == "docx"

    def test_unknown_format_returns_empty(self):
        assert _parse_generate_office_format('{"output_format":"pdf"}') == ""

    def test_empty_string_returns_empty(self):
        assert _parse_generate_office_format("") == ""

    def test_none_returns_empty(self):
        assert _parse_generate_office_format(None) == ""

    def test_invalid_json_returns_empty(self):
        assert _parse_generate_office_format("not json") == ""

    def test_non_dict_returns_empty(self):
        assert _parse_generate_office_format("[1,2]") == ""

    def test_missing_key_returns_empty(self):
        assert _parse_generate_office_format('{"other":"val"}') == ""

    def test_blank_format_returns_empty(self):
        assert _parse_generate_office_format('{"output_format":"  "}') == ""


# ---------------------------------------------------------------------------
# _tool_key
# ---------------------------------------------------------------------------
class TestToolKey:
    def test_combines_name_and_args(self):
        result = _tool_key("mytool", '{"a":1}')
        assert result.startswith("mytool::")
        assert "a" in result


# ---------------------------------------------------------------------------
# _resolve_chat_model_for_client
# ---------------------------------------------------------------------------
class TestResolveChatModelForClient:
    def test_explicit_model_takes_precedence(self):
        assert _resolve_chat_model_for_client(None, "gpt-4") == "gpt-4"

    def test_modstore_client_with_default_model(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = True
        client.default_model = "my-model"
        client.default_provider = "prov"
        assert _resolve_chat_model_for_client(client, None) == "prov/my-model"

    def test_modstore_client_model_only(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = True
        client.default_model = "my-model"
        client.default_provider = ""
        assert _resolve_chat_model_for_client(client, None) == "my-model"

    def test_modstore_client_no_model_falls_back(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = True
        client.default_model = ""
        client.default_provider = "prov"
        with patch(
            "app.application.workflow.legacy_chat_adapter.resolve_chat_model",
            return_value="fallback-model",
        ):
            assert _resolve_chat_model_for_client(client, None) == "fallback-model"

    def test_non_modstore_client_falls_back(self):
        client = MagicMock()
        client.is_modstore_openai_compatible = False
        with patch(
            "app.application.workflow.legacy_chat_adapter.resolve_chat_model",
            return_value="fallback-model",
        ):
            assert _resolve_chat_model_for_client(client, None) == "fallback-model"

    def test_none_client_falls_back(self):
        with patch(
            "app.application.workflow.legacy_chat_adapter.resolve_chat_model",
            return_value="fallback-model",
        ):
            assert _resolve_chat_model_for_client(None, None) == "fallback-model"


# ---------------------------------------------------------------------------
# _tool_stream_call_label
# ---------------------------------------------------------------------------
class TestToolStreamCallLabel:
    def test_generate_office_docx(self):
        assert _tool_stream_call_label(
            "generate_office_document", '{"output_format":"docx"}'
        ) == "生成 Word 文档（.docx）"

    def test_generate_office_xlsx(self):
        assert _tool_stream_call_label(
            "generate_office_document", '{"output_format":"xlsx"}'
        ) == "生成 Excel 工作簿（.xlsx）"

    def test_generate_office_unknown_format(self):
        result = _tool_stream_call_label("generate_office_document", '{"output_format":"pdf"}')
        assert result == "生成可下载文档（Word 或 Excel）"

    def test_known_tool_label(self):
        assert _tool_stream_call_label("excel_analysis", "{}") == "读取或分析 Excel"

    def test_unknown_tool_returns_name(self):
        assert _tool_stream_call_label("custom_tool", "{}") == "custom_tool"


# ---------------------------------------------------------------------------
# _slow_tool_wait_message
# ---------------------------------------------------------------------------
class TestSlowToolWaitMessage:
    def test_import_excel(self):
        msg = _slow_tool_wait_message("import_excel_to_database", "{}")
        assert msg is not None
        assert "导入数据库" in msg

    def test_generate_office_docx(self):
        msg = _slow_tool_wait_message(
            "generate_office_document", '{"output_format":"docx"}'
        )
        assert msg is not None
        assert "Word" in msg

    def test_generate_office_xlsx(self):
        msg = _slow_tool_wait_message(
            "generate_office_document", '{"output_format":"xlsx"}'
        )
        assert msg is not None
        assert "Excel" in msg

    def test_generate_office_no_format(self):
        msg = _slow_tool_wait_message("generate_office_document", "{}")
        assert msg is not None
        assert "可下载文件" in msg

    def test_other_tool_returns_none(self):
        assert _slow_tool_wait_message("excel_analysis", "{}") is None


# ---------------------------------------------------------------------------
# _post_tool_round_hint
# ---------------------------------------------------------------------------
class TestPostToolRoundHint:
    def test_docx_ok(self):
        tcs = [_Tc("1", "generate_office_document", '{"output_format":"docx"}')]
        payloads = [{"success": True, "download_url": "http://x"}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "Word" in hint

    def test_xlsx_ok(self):
        tcs = [_Tc("1", "generate_office_document", '{"output_format":"xlsx"}')]
        payloads = [{"success": True, "download_url": "http://x"}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "Excel" in hint

    def test_import_ok(self):
        tcs = [_Tc("1", "import_excel_to_database", "{}")]
        payloads = [{"success": True}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "导入" in hint

    def test_docx_and_xlsx_ok(self):
        tcs = [
            _Tc("1", "generate_office_document", '{"output_format":"docx"}'),
            _Tc("2", "generate_office_document", '{"output_format":"xlsx"}'),
        ]
        payloads = [
            {"success": True, "download_url": "http://x"},
            {"success": True, "download_url": "http://y"},
        ]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "Word" in hint and "Excel" in hint

    def test_failure_message(self):
        tcs = [_Tc("1", "generate_office_document", '{"output_format":"docx"}')]
        payloads = [{"success": False, "message": "some error"}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "未成功" in hint

    def test_duplicate_tool_call_error(self):
        tcs = [_Tc("1", "generate_office_document", '{"output_format":"docx"}')]
        payloads = [{"error": "duplicate_tool_call", "hint": "dup"}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "未成功" in hint

    def test_no_download_url(self):
        tcs = [_Tc("1", "generate_office_document", '{"output_format":"docx"}')]
        payloads = [{"success": True}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "未成功" in hint

    def test_requires_token_skipped(self):
        tcs = [_Tc("1", "import_excel_to_database", "{}")]
        payloads = [{"requires_token": True}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "工具已返回结果" in hint

    def test_empty_tool_calls(self):
        hint = _post_tool_round_hint([])
        assert "工具已返回结果" in hint

    def test_generic_fallback(self):
        tcs = [_Tc("1", "unknown_tool", "{}")]
        payloads = [{}]
        hint = _post_tool_round_hint(tcs, payloads)
        assert "工具已返回结果" in hint


# ---------------------------------------------------------------------------
# _planner_tools_max_workers
# ---------------------------------------------------------------------------
class TestPlannerToolsMaxWorkers:
    def test_default_is_8(self, monkeypatch):
        monkeypatch.delenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", raising=False)
        assert _planner_tools_max_workers() == 8

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", "4")
        assert _planner_tools_max_workers() == 4

    def test_invalid_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", "abc")
        assert _planner_tools_max_workers() == 8

    def test_clamped_to_1_minimum(self, monkeypatch):
        monkeypatch.setenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", "0")
        assert _planner_tools_max_workers() == 1

    def test_clamped_to_32_maximum(self, monkeypatch):
        monkeypatch.setenv("FHD_PLANNER_TOOLS_MAX_PARALLEL", "100")
        assert _planner_tools_max_workers() == 32


# ---------------------------------------------------------------------------
# reset_planner_tool_dedup_state
# ---------------------------------------------------------------------------
class TestResetPlannerToolDedupState:
    def test_clears_dedup_set(self):
        from app.application.workflow.legacy_chat_adapter import _TOOL_DEDUP

        _TOOL_DEDUP.add("test_key")
        reset_planner_tool_dedup_state()
        assert len(_TOOL_DEDUP) == 0


# ---------------------------------------------------------------------------
# append_tool_messages
# ---------------------------------------------------------------------------
class TestAppendToolMessages:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_empty_tool_calls_returns_none(self):
        result = append_tool_messages([], [], workspace_root=None, execute_tool=MagicMock())
        assert result is None

    def test_single_tool_serial_execution(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        payload = json.loads(messages[0]["content"])
        assert payload["success"] is True

    def test_requires_token_returns_early(self):
        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )
        tcs = [_Tc("tc1", "import_excel_to_database", "{}")]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is not None
        assert result.get("requires_token") is True

    def test_duplicate_tool_call(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        messages1: list = []
        append_tool_messages(messages1, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        messages2: list = []
        append_tool_messages(messages2, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        payload = json.loads(messages2[0]["content"])
        assert payload.get("error") == "duplicate_tool_call"

    def test_parallel_execution(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [
            _Tc("tc1", "excel_analysis", '{"q":"a"}'),
            _Tc("tc2", "excel_chart_recommend", '{"q":"b"}'),
        ]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 2

    def test_token_sensitive_tools_force_serial(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [
            _Tc("tc1", "import_excel_to_database", '{"q":"a"}'),
            _Tc("tc2", "excel_analysis", '{"q":"b"}'),
        ]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 2

    def test_invalid_json_args_handled(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", "not json")]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 1

    def test_enrich_excel_tool_arguments_called(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"query":"test"}')]
        messages: list = []
        with patch(
            "app.application.workflow.legacy_chat_adapter.enrich_excel_tool_arguments",
            return_value={"query": "enriched"},
        ) as mock_enrich:
            append_tool_messages(
                messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
            )
            mock_enrich.assert_called_once()


# ---------------------------------------------------------------------------
# chat (non-streaming)
# ---------------------------------------------------------------------------
class TestChat:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_chat_returns_dict_on_text_response(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "Hello!"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            result = chat("hi", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert result["text"] == "Hello!"

    def test_chat_with_tool_calls(self):
        mock_client = MagicMock()
        # First call: returns tool call
        mock_msg1 = MagicMock()
        mock_msg1.content = ""
        tc = _Tc("tc1", "excel_analysis", '{"query":"test"}')
        mock_msg1.tool_calls = [tc]
        mock_choice1 = MagicMock()
        mock_choice1.message = mock_msg1
        mock_resp1 = MagicMock()
        mock_resp1.choices = [mock_choice1]

        # Second call: returns text
        mock_msg2 = MagicMock()
        mock_msg2.content = "Done!"
        mock_msg2.tool_calls = None
        mock_choice2 = MagicMock()
        mock_choice2.message = mock_msg2
        mock_resp2 = MagicMock()
        mock_resp2.choices = [mock_choice2]

        mock_client.chat.completions.create.side_effect = [mock_resp1, mock_resp2]
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(return_value='{"success": true}')

        with (
            patch(
                "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.application.workflow.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            result = chat("analyze", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert "调用工具" in result["thinking_steps"]

    def test_chat_max_iterations_reached(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = ""
        tc = _Tc("tc1", "excel_analysis", '{"query":"test"}')
        mock_msg.tool_calls = [tc]
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(return_value='{"success": true}')

        with (
            patch(
                "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.application.workflow.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            result = chat("analyze", client=mock_client, model="test-model", max_iterations=1)
        assert isinstance(result, dict)
        assert "最大迭代" in result["text"]

    def test_chat_requires_token_returns_json_string(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = ""
        tc = _Tc("tc1", "import_excel_to_database", '{}')
        mock_msg.tool_calls = [tc]
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )

        with (
            patch(
                "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.application.workflow.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            result = chat("import", client=mock_client, model="test-model")
        assert isinstance(result, str)
        data = json.loads(result)
        assert data["requires_token"] is True


# ---------------------------------------------------------------------------
# chat_stream_text
# ---------------------------------------------------------------------------
class TestChatStreamText:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_yields_text_content(self):
        mock_client = MagicMock()
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = MagicMock(content="Hello")
        chunk1.choices[0].finish_reason = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock(content=" World")
        chunk2.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            parts = list(chat_stream_text("hi", client=mock_client, model="test-model"))
        assert "Hello" in parts
        assert " World" in parts

    def test_yields_tool_call_label(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        delta = MagicMock()
        delta.content = None
        delta.tool_calls = [MagicMock()]
        delta.tool_calls[0].index = 0
        delta.tool_calls[0].id = "tc1"
        fn = MagicMock()
        fn.name = "excel_analysis"
        fn.arguments = '{"query":"test"}'
        delta.tool_calls[0].function = fn
        chunk.choices[0].delta = delta
        chunk.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(return_value='{"success": true}')

        with (
            patch(
                "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.application.workflow.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            parts = list(chat_stream_text("analyze", client=mock_client, model="test-model", max_iterations=1))
        text_parts = [p for p in parts if isinstance(p, str)]
        assert any("调用工具" in p for p in text_parts)

    def test_yields_requires_token_dict(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        delta = MagicMock()
        delta.content = None
        delta.tool_calls = [MagicMock()]
        delta.tool_calls[0].index = 0
        delta.tool_calls[0].id = "tc1"
        fn = MagicMock()
        fn.name = "import_excel_to_database"
        fn.arguments = '{}'
        delta.tool_calls[0].function = fn
        chunk.choices[0].delta = delta
        chunk.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )

        with (
            patch(
                "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.application.workflow.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            parts = list(chat_stream_text("import", client=mock_client, model="test-model"))
        dict_parts = [p for p in parts if isinstance(p, dict)]
        assert any(p.get("_planner_sse") == "requires_token" for p in dict_parts)


# ---------------------------------------------------------------------------
# chat_stream_sse_events
# ---------------------------------------------------------------------------
class TestChatStreamSseEvents:
    def setup_method(self):
        reset_planner_tool_dedup_state()

    def test_yields_token_and_done_events(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hi")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            events = list(
                chat_stream_sse_events("hi", client=mock_client, model="test-model")
            )
        types = [e["type"] for e in events]
        assert "token" in types
        assert "done" in types

    def test_requires_token_event(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        delta = MagicMock()
        delta.content = None
        delta.tool_calls = [MagicMock()]
        delta.tool_calls[0].index = 0
        delta.tool_calls[0].id = "tc1"
        fn = MagicMock()
        fn.name = "import_excel_to_database"
        fn.arguments = '{}'
        delta.tool_calls[0].function = fn
        chunk.choices[0].delta = delta
        chunk.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )

        with (
            patch(
                "app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.application.workflow.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            events = list(
                chat_stream_sse_events("import", client=mock_client, model="test-model")
            )
        types = [e["type"] for e in events]
        assert "requires_token" in types
