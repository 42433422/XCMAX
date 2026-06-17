"""Tests for app.application.employee_runtime.agent_loop."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from app.application.employee_runtime.agent_loop import (
    _format_tool_calls,
    _parse_args,
    default_employee_tools,
    run_employee_agent_loop,
)


class TestParseArgs:
    def test_valid_json(self):
        result = _parse_args('{"key": "value"}')
        assert result == {"key": "value"}

    def test_empty_string(self):
        result = _parse_args("")
        assert result == {}

    def test_none(self):
        result = _parse_args(None)
        assert result == {}

    def test_invalid_json(self):
        result = _parse_args("not json")
        assert result == {}

    def test_non_dict_json(self):
        result = _parse_args("[1, 2, 3]")
        assert result == {}

    def test_nested_json(self):
        result = _parse_args('{"a": {"b": 1}}')
        assert result == {"a": {"b": 1}}


class TestFormatToolCalls:
    def test_empty_list(self):
        assert _format_tool_calls([]) == []

    def test_format_single_tool_call(self):
        tc = MagicMock()
        tc.id = "call_123"
        fn = MagicMock()
        fn.name = "search"
        fn.arguments = '{"query": "test"}'
        tc.function = fn

        result = _format_tool_calls([tc])
        assert len(result) == 1
        assert result[0]["id"] == "call_123"
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"

    def test_missing_attributes(self):
        tc = MagicMock(spec=[])
        result = _format_tool_calls([tc])
        assert len(result) == 1
        assert result[0]["id"] == ""


class TestDefaultEmployeeTools:
    @patch("app.application.tools.workflow.get_workflow_tool_registry", return_value=None)
    def test_none_registry_returns_empty(self, mock_reg):
        result = default_employee_tools()
        assert result == []

    @patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=True)
    @patch("app.application.tools.workflow.get_workflow_tool_registry")
    def test_filters_employee_tools(self, mock_reg, mock_is_emp):
        spec = {"function": {"name": "employee_tool"}}
        mock_reg.return_value = [spec]
        result = default_employee_tools()
        assert len(result) == 0

    @patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False)
    @patch("app.application.tools.workflow.get_workflow_tool_registry")
    def test_keeps_non_employee_tools(self, mock_reg, mock_is_emp):
        spec = {"function": {"name": "normal_tool"}}
        mock_reg.return_value = [spec]
        result = default_employee_tools()
        assert len(result) == 1

    @patch(
        "app.application.tools.workflow.get_workflow_tool_registry",
        side_effect=ImportError("no module"),
    )
    def test_import_error_returns_empty(self, mock_reg):
        result = default_employee_tools()
        assert result == []


class TestRunEmployeeAgentLoop:
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_llm_unavailable_returns_degraded(self, mock_key):
        mock_key.side_effect = RuntimeError("No API key")
        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
        )
        assert result["degraded"] is True
        assert result["ok"] is False

    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-4")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_simple_text_response(self, mock_key, mock_client, mock_model):
        mock_completion = MagicMock()
        msg = MagicMock()
        msg.content = "Hello, I can help with that."
        msg.tool_calls = None
        mock_completion.choices = [MagicMock(message=msg)]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_completion
        mock_client.return_value = mock_client_instance

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
            tools=[],
        )
        assert result["ok"] is True
        assert result["output"] == "Hello, I can help with that."
        assert result["rounds"] == 1

    @patch("app.application.tools.workflow.execute_workflow_tool", return_value='{"success": true}')
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-4")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_max_iterations_reached(self, mock_key, mock_client, mock_model, mock_exec):
        mock_completion = MagicMock()
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "tool1"
        tc.function.arguments = "{}"
        msg = MagicMock()
        msg.content = ""
        msg.tool_calls = [tc]
        mock_completion.choices = [MagicMock(message=msg)]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_completion
        mock_client.return_value = mock_client_instance

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
            tools=[{"type": "function", "function": {"name": "tool1"}}],
            max_iterations=2,
        )
        assert result["max_iterations_reached"] is True

    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-4")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_llm_call_recoverable_error(self, mock_key, mock_client, mock_model):
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = ConnectionError("timeout")
        mock_client.return_value = mock_client_instance

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
        )
        assert result["ok"] is False
        assert "timeout" in result["error"]

    @patch("app.application.tools.workflow.execute_workflow_tool", return_value='{"success": true}')
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-4")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_tool_call_with_gate_blocked(self, mock_key, mock_client, mock_model, mock_exec):
        mock_completion = MagicMock()
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "dangerous_tool"
        tc.function.arguments = '{"action": "delete"}'
        msg = MagicMock()
        msg.content = ""
        msg.tool_calls = [tc]
        mock_completion.choices = [MagicMock(message=msg)]

        # Second iteration: no tool calls, text response
        mock_completion2 = MagicMock()
        msg2 = MagicMock()
        msg2.content = "Tool was blocked"
        msg2.tool_calls = None
        mock_completion2.choices = [MagicMock(message=msg2)]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = [
            mock_completion,
            mock_completion2,
        ]
        mock_client.return_value = mock_client_instance

        gate = MagicMock(return_value={"ok": False, "reason": "not allowed"})

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
            tools=[{"type": "function", "function": {"name": "dangerous_tool"}}],
            gate=gate,
        )
        assert result["ok"] is True
        assert any(t.get("blocked") for t in result["tool_calls"])

    @patch("app.application.tools.workflow.execute_workflow_tool", side_effect=RuntimeError("tool failed"))
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-4")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_tool_execution_error(self, mock_key, mock_client, mock_model, mock_exec):
        mock_completion = MagicMock()
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "tool1"
        tc.function.arguments = "{}"
        msg = MagicMock()
        msg.content = ""
        msg.tool_calls = [tc]
        mock_completion.choices = [MagicMock(message=msg)]

        # Second iteration: no tool calls
        mock_completion2 = MagicMock()
        msg2 = MagicMock()
        msg2.content = "Done"
        msg2.tool_calls = None
        mock_completion2.choices = [MagicMock(message=msg2)]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.side_effect = [
            mock_completion,
            mock_completion2,
        ]
        mock_client.return_value = mock_client_instance

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
            tools=[{"type": "function", "function": {"name": "tool1"}}],
        )
        assert result["ok"] is True

    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-4")
    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    def test_default_system_prompt(self, mock_key, mock_client, mock_model):
        mock_completion = MagicMock()
        msg = MagicMock()
        msg.content = "Response"
        msg.tool_calls = None
        mock_completion.choices = [MagicMock(message=msg)]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_completion
        mock_client.return_value = mock_client_instance

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="",
            task="do something",
        )
        assert result["ok"] is True
        # Verify the system prompt was set to default
        call_args = mock_client_instance.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        assert messages[0]["content"] == "你是智能员工助手。"
