"""测试 legacy_chat_adapter 的补充分支覆盖。

覆盖目标（test_legacy_chat_adapter.py 未覆盖的方法与分支）：
- _should_replace_tool_result: 各分支（previous None / new None / success 组合 / download_url）
- _record_tool_result: 各分支（payload None / requires_token / download_url / replace）
- _tool_action_from_payload: 各分支（action 存在 / excel 工具 / 默认）
- _append_last_tool_record: 各分支（JSON 解析失败 / 非 dict / 正常）
- _attach_last_tool_records: 各分支（有记录 / 无记录）
- clear_last_tool_result: 清空记录
- get_last_tool_records: 各分支（无记录 / 有记录 / 非列表）
- get_last_tool_result: 各分支（无记录 / 有记录 / output 非 dict）
- reset_last_tool_result: 重置 ContextVar
- _call_model_completion: 各分支（client None / client 提供）
- append_tool_messages: 补充分支（并行重复 / 并行 requires_token / 无 execute_tool）
- chat: 补充分支（system_prompt / runtime_context / 无 tool_calls / tool_outputs 累积）
- chat_stream_text: 补充分支（delta None / tool_calls 跨 chunk 累积 / finish_reason / post_tool_round_hint）
- chat_stream_sse_events: 补充分支（token_description / message fallback）
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.legacy.chat.legacy_chat_adapter import (
    _LAST_TOOL_RESULT,
    _LAST_TOOL_TRACE,
    _TOOL_DEDUP,
    _append_last_tool_record,
    _attach_last_tool_records,
    _call_model_completion,
    _record_tool_result,
    _should_replace_tool_result,
    _tool_action_from_payload,
    append_tool_messages,
    chat,
    chat_stream_sse_events,
    chat_stream_text,
    clear_last_tool_result,
    get_last_tool_records,
    get_last_tool_result,
    reset_last_tool_result,
    reset_planner_tool_dedup_state,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Fn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _Tc:
    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.function = _Fn(name, arguments)


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前重置全局状态，避免污染。"""
    reset_planner_tool_dedup_state()
    reset_last_tool_result()
    yield
    reset_planner_tool_dedup_state()
    reset_last_tool_result()


# ---------------------------------------------------------------------------
# _should_replace_tool_result
# ---------------------------------------------------------------------------


class TestShouldReplaceToolResultEdge:
    """_should_replace_tool_result 的分支覆盖。"""

    def test_previous_none_new_none(self):
        assert _should_replace_tool_result(None, None) is False

    def test_previous_none_new_empty(self):
        assert _should_replace_tool_result(None, {}) is False

    def test_previous_none_new_with_data(self):
        assert _should_replace_tool_result(None, {"success": True}) is True

    def test_previous_empty_new_none(self):
        assert _should_replace_tool_result({}, None) is False

    def test_previous_empty_new_empty(self):
        assert _should_replace_tool_result({}, {}) is False

    def test_new_success_previous_not_success(self):
        previous = {"success": False}
        new = {"success": True}
        assert _should_replace_tool_result(previous, new) is True

    def test_previous_success_new_not_success(self):
        previous = {"success": True}
        new = {"success": False}
        assert _should_replace_tool_result(previous, new) is False

    def test_both_success_no_download_url_change(self):
        previous = {"success": True}
        new = {"success": True}
        assert _should_replace_tool_result(previous, new) is False

    def test_both_success_previous_no_url_new_has_url(self):
        previous = {"success": True}
        new = {"success": True, "download_url": "http://x"}
        assert _should_replace_tool_result(previous, new) is True

    def test_both_success_previous_has_url_new_has_url(self):
        previous = {"success": True, "download_url": "http://old"}
        new = {"success": True, "download_url": "http://new"}
        assert _should_replace_tool_result(previous, new) is False

    def test_both_success_previous_has_url_new_no_url(self):
        previous = {"success": True, "download_url": "http://old"}
        new = {"success": True}
        assert _should_replace_tool_result(previous, new) is False

    def test_both_not_success(self):
        previous = {"success": False}
        new = {"success": False}
        assert _should_replace_tool_result(previous, new) is False

    def test_previous_success_true_new_success_none(self):
        previous = {"success": True}
        new = {}
        assert _should_replace_tool_result(previous, new) is False


# ---------------------------------------------------------------------------
# _record_tool_result
# ---------------------------------------------------------------------------


class TestRecordToolResultEdge:
    """_record_tool_result 的分支覆盖。"""

    def test_record_none_payload_does_nothing(self):
        _record_tool_result("tool1", None)
        assert _LAST_TOOL_RESULT.get() is None

    def test_record_requires_token_does_nothing(self):
        _record_tool_result("tool1", {"requires_token": True, "success": True})
        assert _LAST_TOOL_RESULT.get() is None

    def test_record_success_no_previous(self):
        _record_tool_result("tool1", {"success": True})
        result = _LAST_TOOL_RESULT.get()
        assert result is not None
        assert result["tool_key"] == "tool1"
        assert result["success"] is True

    def test_record_with_download_url(self):
        _record_tool_result("tool1", {"success": True, "download_url": "http://x"})
        result = _LAST_TOOL_RESULT.get()
        assert result is not None
        assert result["download_url"] == "http://x"

    def test_record_does_not_replace_when_previous_better(self):
        _record_tool_result("tool1", {"success": True, "download_url": "http://old"})
        _record_tool_result("tool2", {"success": False})
        result = _LAST_TOOL_RESULT.get()
        assert result["tool_key"] == "tool1"

    def test_record_replaces_when_new_better(self):
        _record_tool_result("tool1", {"success": False})
        _record_tool_result("tool2", {"success": True})
        result = _LAST_TOOL_RESULT.get()
        assert result["tool_key"] == "tool2"

    def test_record_replaces_when_new_has_download_url(self):
        _record_tool_result("tool1", {"success": True})
        _record_tool_result("tool2", {"success": True, "download_url": "http://x"})
        result = _LAST_TOOL_RESULT.get()
        assert result["tool_key"] == "tool2"

    def test_record_payload_without_success(self):
        _record_tool_result("tool1", {"message": "no success field"})
        result = _LAST_TOOL_RESULT.get()
        assert result is not None
        assert result["success"] is None


# ---------------------------------------------------------------------------
# _tool_action_from_payload
# ---------------------------------------------------------------------------


class TestToolActionFromPayloadEdge:
    """_tool_action_from_payload 的分支覆盖。"""

    def test_action_from_params(self):
        assert _tool_action_from_payload("any_tool", {"action": "read"}) == "read"

    def test_action_from_params_with_whitespace(self):
        assert _tool_action_from_payload("any_tool", {"action": "  write  "}) == "write"

    def test_action_empty_string(self):
        assert _tool_action_from_payload("any_tool", {"action": ""}) == "execute"

    def test_action_none(self):
        assert _tool_action_from_payload("any_tool", {"action": None}) == "execute"

    def test_excel_analysis_default_read(self):
        assert _tool_action_from_payload("excel_analysis", {}) == "read"

    def test_excel_schema_understand_default_read(self):
        assert _tool_action_from_payload("excel_schema_understand", {}) == "read"

    def test_other_tool_default_execute(self):
        assert _tool_action_from_payload("custom_tool", {}) == "execute"

    def test_excel_analysis_action_overrides(self):
        assert _tool_action_from_payload("excel_analysis", {"action": "write"}) == "write"

    def test_empty_params(self):
        assert _tool_action_from_payload("any_tool", {}) == "execute"


# ---------------------------------------------------------------------------
# _append_last_tool_record
# ---------------------------------------------------------------------------


class TestAppendLastToolRecordEdge:
    """_append_last_tool_record 的分支覆盖。"""

    def test_append_valid_json(self):
        tc = _Tc("tc1", "excel_analysis", '{"query":"test"}')
        _append_last_tool_record(tc, "excel_analysis", '{"query":"test"}', {"success": True})
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["tool_id"] == "excel_analysis"
        assert records[0]["action"] == "read"
        assert records[0]["params"] == {"query": "test"}
        assert records[0]["success"] is True
        assert records[0]["tool_call_id"] == "tc1"

    def test_append_empty_arguments(self):
        tc = _Tc("tc1", "custom_tool", "")
        _append_last_tool_record(tc, "custom_tool", "", {"success": False})
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["params"] == {}
        assert records[0]["action"] == "execute"
        assert records[0]["success"] is False

    def test_append_whitespace_arguments(self):
        tc = _Tc("tc1", "custom_tool", "   ")
        _append_last_tool_record(tc, "custom_tool", "   ", {"success": True})
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["params"] == {}

    def test_append_invalid_json(self):
        tc = _Tc("tc1", "custom_tool", "not json")
        _append_last_tool_record(tc, "custom_tool", "not json", {"success": True})
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["params"] == {}

    def test_append_non_dict_json(self):
        tc = _Tc("tc1", "custom_tool", "[1,2,3]")
        _append_last_tool_record(tc, "custom_tool", "[1,2,3]", {"success": True})
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["params"] == {}

    def test_append_non_dict_payload(self):
        tc = _Tc("tc1", "custom_tool", "{}")
        _append_last_tool_record(tc, "custom_tool", "{}", "not a dict")
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["output"] == {"message": "not a dict"}
        assert records[0]["success"] is False

    def test_append_none_payload(self):
        tc = _Tc("tc1", "custom_tool", "{}")
        _append_last_tool_record(tc, "custom_tool", "{}", None)
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["output"] == {"message": ""}
        assert records[0]["success"] is False

    def test_append_multiple_records(self):
        tc1 = _Tc("tc1", "tool1", "{}")
        tc2 = _Tc("tc2", "tool2", "{}")
        _append_last_tool_record(tc1, "tool1", "{}", {"success": True})
        _append_last_tool_record(tc2, "tool2", "{}", {"success": False})
        records = get_last_tool_records()
        assert len(records) == 2
        assert records[0]["tool_id"] == "tool1"
        assert records[1]["tool_id"] == "tool2"

    def test_append_no_tc_id(self):
        tc = MagicMock()
        tc.id = ""
        _append_last_tool_record(tc, "tool1", "{}", {"success": True})
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0]["tool_call_id"] == ""

    def test_append_no_tc_attr(self):
        tc = MagicMock(spec=[])  # 无 id 属性
        _append_last_tool_record(tc, "tool1", "{}", {"success": True})
        records = get_last_tool_records()
        assert len(records) == 1


# ---------------------------------------------------------------------------
# _attach_last_tool_records
# ---------------------------------------------------------------------------


class TestAttachLastToolRecordsEdge:
    """_attach_last_tool_records 的分支覆盖。"""

    def test_attach_with_records(self):
        tc = _Tc("tc1", "tool1", "{}")
        _append_last_tool_record(tc, "tool1", "{}", {"success": True})
        payload = {"response": "test"}
        result = _attach_last_tool_records(payload)
        assert "legacy_tool_records" in result
        assert len(result["legacy_tool_records"]) == 1

    def test_attach_without_records(self):
        payload = {"response": "test"}
        result = _attach_last_tool_records(payload)
        assert "legacy_tool_records" not in result
        assert result == {"response": "test"}

    def test_attach_returns_same_dict(self):
        payload = {"response": "test"}
        result = _attach_last_tool_records(payload)
        assert result is payload


# ---------------------------------------------------------------------------
# clear_last_tool_result / get_last_tool_records / get_last_tool_result
# ---------------------------------------------------------------------------


class TestClearAndGetLastToolEdge:
    """clear_last_tool_result / get_last_tool_records / get_last_tool_result 的分支覆盖。"""

    def test_clear_resets_records(self):
        tc = _Tc("tc1", "tool1", "{}")
        _append_last_tool_record(tc, "tool1", "{}", {"success": True})
        assert len(get_last_tool_records()) == 1
        clear_last_tool_result()
        assert get_last_tool_records() == []

    def test_get_last_tool_records_empty(self):
        assert get_last_tool_records() == []

    def test_get_last_tool_records_returns_deep_copy(self):
        tc = _Tc("tc1", "tool1", '{"key":"value"}')
        _append_last_tool_record(tc, "tool1", '{"key":"value"}', {"success": True})
        records1 = get_last_tool_records()
        records1[0]["tool_id"] = "modified"
        records2 = get_last_tool_records()
        assert records2[0]["tool_id"] == "tool1"

    def test_get_last_tool_result_empty(self):
        assert get_last_tool_result() == {}

    def test_get_last_tool_result_with_dict_output(self):
        tc = _Tc("tc1", "tool1", '{"q":"test"}')
        _append_last_tool_record(tc, "tool1", '{"q":"test"}', {"success": True, "data": "x"})
        result = get_last_tool_result()
        assert result["success"] is True
        assert result["data"] == "x"
        assert result["tool_key"] == "tool1"
        assert result["tool_name"] == "tool1"
        assert result["tool_call_id"] == "tc1"
        assert result["tool_params"] == {"q": "test"}
        assert "_tool_records" in result

    def test_get_last_tool_result_with_non_dict_output(self):
        tc = _Tc("tc1", "tool1", "{}")
        _append_last_tool_record(tc, "tool1", "{}", "string output")
        result = get_last_tool_result()
        assert result["message"] == "string output"
        assert result["tool_key"] == "tool1"

    def test_get_last_tool_result_with_none_output(self):
        tc = _Tc("tc1", "tool1", "{}")
        _append_last_tool_record(tc, "tool1", "{}", None)
        result = get_last_tool_result()
        assert result["message"] == ""

    def test_reset_last_tool_result(self):
        _record_tool_result("tool1", {"success": True})
        assert _LAST_TOOL_RESULT.get() is not None
        reset_last_tool_result()
        assert _LAST_TOOL_RESULT.get() is None

    def test_get_last_tool_records_filters_non_dict(self):
        # 直接操作内部状态来测试过滤
        _LAST_TOOL_TRACE.records = ["not a dict", {"valid": "record"}]
        records = get_last_tool_records()
        assert len(records) == 1
        assert records[0] == {"valid": "record"}

    def test_get_last_tool_records_non_list_records(self):
        _LAST_TOOL_TRACE.records = "not a list"
        records = get_last_tool_records()
        assert records == []


# ---------------------------------------------------------------------------
# _call_model_completion
# ---------------------------------------------------------------------------


class TestCallModelCompletionEdge:
    """_call_model_completion 的分支覆盖。"""

    def test_call_with_explicit_client(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "  response text  "
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._resolve_chat_model_for_client",
            return_value="test-model",
        ):
            result = _call_model_completion(
                [{"role": "user", "content": "hi"}],
                model="explicit-model",
                client=mock_client,
            )
        assert result == "response text"
        mock_client.chat.completions.create.assert_called_once()

    def test_call_without_client_uses_default(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "default response"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.require_api_key",
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_openai_compatible_client",
                return_value=mock_client,
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_model_for_client",
                return_value="default-model",
            ),
        ):
            result = _call_model_completion([{"role": "user", "content": "hi"}])
        assert result == "default response"

    def test_call_with_none_content(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._resolve_chat_model_for_client",
            return_value="test-model",
        ):
            result = _call_model_completion(
                [{"role": "user", "content": "hi"}],
                client=mock_client,
            )
        assert result == ""


# ---------------------------------------------------------------------------
# append_tool_messages 补充分支
# ---------------------------------------------------------------------------


class TestAppendToolMessagesExtraEdge:
    """append_tool_messages 的补充分支覆盖。"""

    def test_parallel_execution_with_duplicate(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [
            _Tc("tc1", "excel_analysis", '{"q":"a"}'),
            _Tc("tc2", "excel_analysis", '{"q":"a"}'),  # 重复
        ]
        messages: list = []
        # 先执行一次让 tc1 进入 dedup
        append_tool_messages([], tcs[:1], workspace_root="/tmp", execute_tool=execute_tool)
        # 第二次执行两个工具，tc1 应该是 duplicate
        reset_planner_tool_dedup_state()
        append_tool_messages([], tcs, workspace_root="/tmp", execute_tool=execute_tool)
        # 只验证不抛异常即可

    def test_parallel_execution_with_requires_token(self):
        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN"}'
        )
        tcs = [
            _Tc("tc1", "excel_analysis", '{"q":"a"}'),
            _Tc("tc2", "excel_chart_recommend", '{"q":"b"}'),
        ]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is not None
        assert result.get("requires_token") is True

    def test_no_execute_tool_uses_resolver(self):
        tcs = [_Tc("tc1", "excel_analysis", '{"q":"test"}')]
        messages: list = []
        mock_execute = MagicMock(return_value='{"success": true}')
        with patch(
            "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
            return_value=mock_execute,
        ):
            result = append_tool_messages(messages, tcs, workspace_root="/tmp")
        assert result is None
        assert len(messages) == 1
        mock_execute.assert_called_once()

    def test_excel_schema_understand_enriched(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_schema_understand", '{"query":"test"}')]
        messages: list = []
        with patch(
            "app.legacy.chat.legacy_chat_adapter.enrich_excel_tool_arguments",
            return_value={"query": "enriched"},
        ) as mock_enrich:
            append_tool_messages(messages, tcs, workspace_root="/tmp", execute_tool=execute_tool)
            mock_enrich.assert_called_once()

    def test_non_dict_args_dict_handled(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "custom_tool", "[1,2,3]")]
        messages: list = []
        result = append_tool_messages(messages, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        assert result is None
        assert len(messages) == 1

    def test_serial_execution_duplicate(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "import_excel_to_database", '{"q":"a"}')]
        messages1: list = []
        append_tool_messages(messages1, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        messages2: list = []
        append_tool_messages(messages2, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        payload = json.loads(messages2[0]["content"])
        assert payload.get("error") == "duplicate_tool_call"

    def test_parallel_execution_success(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [
            _Tc("tc1", "excel_analysis", '{"q":"a"}'),
            _Tc("tc2", "excel_chart_recommend", '{"q":"b"}'),
            _Tc("tc3", "excel_schema_understand", '{"q":"c"}'),
        ]
        messages: list = []
        result = append_tool_messages(
            messages, tcs, workspace_root="/tmp", execute_tool=execute_tool
        )
        assert result is None
        assert len(messages) == 3

    def test_tool_call_id_in_message(self):
        execute_tool = MagicMock(return_value='{"success": true}')
        tcs = [_Tc("tc1", "excel_analysis", '{"q":"test"}')]
        messages: list = []
        append_tool_messages(messages, tcs, workspace_root="/tmp", execute_tool=execute_tool)
        assert messages[0]["tool_call_id"] == "tc1"
        assert messages[0]["role"] == "tool"


# ---------------------------------------------------------------------------
# chat 补充分支
# ---------------------------------------------------------------------------


class TestChatExtraEdge:
    """chat 的补充分支覆盖。"""

    def test_chat_with_system_prompt(self):
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
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            result = chat("hi", system_prompt="You are helpful", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert result["text"] == "Hello!"

    def test_chat_with_runtime_context(self):
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
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            result = chat(
                "hi",
                runtime_context={"key": "value"},
                client=mock_client,
                model="test-model",
            )
        assert isinstance(result, dict)
        assert result["text"] == "Hello!"

    def test_chat_with_tool_outputs_accumulation(self):
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
        mock_msg2.content = "Final response"
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
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            result = chat("analyze", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert "调用工具" in result["thinking_steps"]
        assert "Final response" in result["response"]
        assert result["text"] == "Final response"

    def test_chat_no_tool_calls_no_tool_outputs(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "Direct response"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            result = chat("hi", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert result["text"] == "Direct response"
        assert result["thinking_steps"] is None
        assert result["response"] == "Direct response"

    def test_chat_with_none_content(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = None
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            result = chat("hi", client=mock_client, model="test-model")
        assert isinstance(result, dict)
        assert result["text"] == ""

    def test_chat_max_iterations_default(self):
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
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            result = chat("analyze", client=mock_client, model="test-model", max_iterations=2)
        assert isinstance(result, dict)
        assert "最大迭代" in result["text"]

    def test_chat_without_client_uses_default(self):
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "Default client response"
        mock_msg.tool_calls = None
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_client.is_modstore_openai_compatible = False

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.require_api_key",
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_openai_compatible_client",
                return_value=mock_client,
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_model_for_client",
                return_value="default-model",
            ),
        ):
            result = chat("hi")
        assert isinstance(result, dict)
        assert result["text"] == "Default client response"


# ---------------------------------------------------------------------------
# chat_stream_text 补充分支
# ---------------------------------------------------------------------------


class TestChatStreamTextExtraEdge:
    """chat_stream_text 的补充分支覆盖。"""

    def test_delta_none_skipped(self):
        mock_client = MagicMock()
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = None  # delta 为 None
        chunk1.choices[0].finish_reason = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock(content="Hello")
        chunk2.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            parts = list(chat_stream_text("hi", client=mock_client, model="test-model"))
        assert "Hello" in parts

    def test_tool_calls_accumulated_across_chunks(self):
        mock_client = MagicMock()
        # First chunk: tool call start
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        delta1 = MagicMock()
        delta1.content = None
        delta1.tool_calls = [MagicMock()]
        delta1.tool_calls[0].index = 0
        delta1.tool_calls[0].id = "tc1"
        fn1 = MagicMock()
        fn1.name = "excel_analysis"
        fn1.arguments = '{"query":"'
        delta1.tool_calls[0].function = fn1
        chunk1.choices[0].delta = delta1
        chunk1.choices[0].finish_reason = None

        # Second chunk: tool call continuation
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        delta2 = MagicMock()
        delta2.content = None
        delta2.tool_calls = [MagicMock()]
        delta2.tool_calls[0].index = 0
        delta2.tool_calls[0].id = None
        fn2 = MagicMock()
        fn2.name = None
        fn2.arguments = 'test"}'
        delta2.tool_calls[0].function = fn2
        chunk2.choices[0].delta = delta2
        chunk2.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(return_value='{"success": true}')

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            parts = list(
                chat_stream_text(
                    "analyze", client=mock_client, model="test-model", max_iterations=1
                )
            )
        text_parts = [p for p in parts if isinstance(p, str)]
        assert any("调用工具" in p for p in text_parts)

    def test_finish_reason_stop_returns(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hello")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            parts = list(chat_stream_text("hi", client=mock_client, model="test-model"))
        assert "Hello" in parts

    def test_post_tool_round_hint_yielded(self):
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
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            parts = list(
                chat_stream_text(
                    "analyze", client=mock_client, model="test-model", max_iterations=1
                )
            )
        # 应该包含 post_tool_round_hint
        text_parts = [p for p in parts if isinstance(p, str)]
        assert any("工具已返回" in p for p in text_parts)

    def test_slow_tool_wait_message_yielded(self):
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
        fn.arguments = "{}"
        delta.tool_calls[0].function = fn
        chunk.choices[0].delta = delta
        chunk.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(return_value='{"success": true}')

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            parts = list(
                chat_stream_text(
                    "import", client=mock_client, model="test-model", max_iterations=1
                )
            )
        text_parts = [p for p in parts if isinstance(p, str)]
        # 应该包含 slow tool wait message
        assert any("导入数据库" in p for p in text_parts)

    def test_with_system_prompt(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hello")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            parts = list(
                chat_stream_text(
                    "hi",
                    system_prompt="You are helpful",
                    client=mock_client,
                    model="test-model",
                )
            )
        assert "Hello" in parts

    def test_with_runtime_context(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hello")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            parts = list(
                chat_stream_text(
                    "hi",
                    runtime_context={"key": "value"},
                    client=mock_client,
                    model="test-model",
                )
            )
        assert "Hello" in parts

    def test_without_client_uses_default(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hello")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter.require_api_key",
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter.get_openai_compatible_client",
                return_value=mock_client,
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_model_for_client",
                return_value="default-model",
            ),
        ):
            parts = list(chat_stream_text("hi"))
        assert "Hello" in parts

    def test_max_iterations_reached(self):
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
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            parts = list(
                chat_stream_text(
                    "analyze", client=mock_client, model="test-model", max_iterations=1
                )
            )
        # 应该有内容产出
        assert len(parts) > 0


# ---------------------------------------------------------------------------
# chat_stream_sse_events 补充分支
# ---------------------------------------------------------------------------


class TestChatStreamSseEventsExtraEdge:
    """chat_stream_sse_events 的补充分支覆盖。"""

    def test_token_description_from_message(self):
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
        fn.arguments = "{}"
        delta.tool_calls[0].function = fn
        chunk.choices[0].delta = delta
        chunk.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "DB_WRITE_TOKEN", "message": "需要数据库写入权限"}'
        )

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            events = list(chat_stream_sse_events("import", client=mock_client, model="test-model"))
        types = [e["type"] for e in events]
        assert "requires_token" in types
        token_event = next(e for e in events if e["type"] == "requires_token")
        assert "需要数据库写入权限" in token_event["token_description"]

    def test_token_description_fallback(self):
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
        fn.arguments = "{}"
        delta.tool_calls[0].function = fn
        chunk.choices[0].delta = delta
        chunk.choices[0].finish_reason = "tool_calls"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        execute_tool = MagicMock(
            return_value='{"requires_token": true, "token_name": "CUSTOM_TOKEN"}'
        )

        with (
            patch(
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            events = list(chat_stream_sse_events("import", client=mock_client, model="test-model"))
        types = [e["type"] for e in events]
        assert "requires_token" in types
        token_event = next(e for e in events if e["type"] == "requires_token")
        assert token_event["token_name"] == "CUSTOM_TOKEN"
        assert "数据库写入授权令牌" in token_event["token_description"]

    def test_token_event_before_done(self):
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
        fn.arguments = "{}"
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
                "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
                return_value=[{"type": "function"}],
            ),
            patch(
                "app.legacy.chat.legacy_chat_adapter._resolve_chat_execute_tool",
                return_value=execute_tool,
            ),
        ):
            events = list(chat_stream_sse_events("import", client=mock_client, model="test-model"))
        # requires_token 事件后不应该有 done 事件
        types = [e["type"] for e in events]
        assert "requires_token" in types
        assert "done" not in types

    def test_normal_text_yields_token_and_done(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hello world")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            events = list(chat_stream_sse_events("hi", client=mock_client, model="test-model"))
        types = [e["type"] for e in events]
        assert "token" in types
        assert "done" in types
        token_events = [e for e in events if e["type"] == "token"]
        assert any("Hello world" in e["text"] for e in token_events)

    def test_with_system_prompt(self):
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock(content="Hello")
        chunk.choices[0].finish_reason = "stop"

        mock_client.chat.completions.create.return_value = iter([chunk])
        mock_client.is_modstore_openai_compatible = False

        with patch(
            "app.legacy.chat.legacy_chat_adapter._get_workflow_tool_registry",
            return_value=[],
        ):
            events = list(
                chat_stream_sse_events(
                    "hi",
                    system_prompt="You are helpful",
                    client=mock_client,
                    model="test-model",
                )
            )
        types = [e["type"] for e in events]
        assert "token" in types
        assert "done" in types
