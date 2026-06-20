"""Tests for app.application.employee_runtime.agent_loop."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime.agent_loop import (
    _format_tool_calls,
    _parse_args,
    default_employee_tools,
    run_employee_agent_loop,
)


class TestParseArgs:
    """Tests for _parse_args helper."""

    def test_parse_valid_json(self) -> None:
        result = _parse_args('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_empty_string(self) -> None:
        result = _parse_args("")
        assert result == {}

    def test_parse_none_like(self) -> None:
        result = _parse_args(None)
        assert result == {}

    def test_parse_invalid_json(self) -> None:
        result = _parse_args("not json at all")
        assert result == {}

    def test_parse_non_dict_json(self) -> None:
        result = _parse_args("[1, 2, 3]")
        assert result == {}

    def test_parse_dict_with_nested_data(self) -> None:
        raw = '{"task": "create_order", "items": [1, 2]}'
        result = _parse_args(raw)
        assert result["task"] == "create_order"
        assert result["items"] == [1, 2]


class TestFormatToolCalls:
    """Tests for _format_tool_calls helper."""

    def test_format_empty_list(self) -> None:
        result = _format_tool_calls([])
        assert result == []

    def test_format_single_tool_call(self) -> None:
        tc = MagicMock()
        tc.id = "call_123"
        fn = MagicMock()
        fn.name = "create_order"
        fn.arguments = '{"order_id": 1}'
        tc.function = fn
        result = _format_tool_calls([tc])
        assert len(result) == 1
        assert result[0]["id"] == "call_123"
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "create_order"
        assert result[0]["function"]["arguments"] == '{"order_id": 1}'

    def test_format_tool_call_with_missing_attrs(self) -> None:
        tc = MagicMock(spec=[])
        result = _format_tool_calls([tc])
        assert len(result) == 1
        assert result[0]["id"] == ""
        assert result[0]["function"]["name"] == ""
        assert result[0]["function"]["arguments"] == ""

    def test_format_multiple_tool_calls(self) -> None:
        tc1 = MagicMock()
        tc1.id = "call_1"
        tc1.function.name = "tool_a"
        tc1.function.arguments = "{}"
        tc2 = MagicMock()
        tc2.id = "call_2"
        tc2.function.name = "tool_b"
        tc2.function.arguments = '{"x": 1}'
        result = _format_tool_calls([tc1, tc2])
        assert len(result) == 2


class TestDefaultEmployeeTools:
    """Tests for default_employee_tools."""

    @patch("app.application.tools.workflow.get_workflow_tool_registry", side_effect=ImportError)
    def test_returns_empty_on_import_error(self, mock_reg: MagicMock) -> None:
        result = default_employee_tools()
        assert result == []

    @patch("app.application.tools.workflow.get_workflow_tool_registry", return_value=None)
    def test_returns_empty_on_none_registry(self, mock_reg: MagicMock) -> None:
        result = default_employee_tools()
        assert result == []


class TestRunEmployeeAgentLoop:
    """Tests for run_employee_agent_loop."""

    @patch(
        "app.infrastructure.llm.client.get_openai_compatible_client",
        side_effect=RuntimeError("no key"),
    )
    @patch("app.infrastructure.llm.client.require_api_key", side_effect=RuntimeError("no key"))
    def test_degraded_when_llm_unavailable(
        self, mock_key: MagicMock, mock_client: MagicMock
    ) -> None:
        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="do something",
        )
        assert result["handler"] == "agent"
        assert result["ok"] is False
        assert result["degraded"] is True
        assert result["rounds"] == 0

    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-test")
    def test_direct_text_response(
        self, mock_model: MagicMock, mock_key: MagicMock, mock_client: MagicMock
    ) -> None:
        msg = MagicMock()
        msg.content = "Hello from assistant"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        completion = MagicMock()
        completion.choices = [choice]
        mock_client.return_value.chat.completions.create.return_value = completion

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="greet",
            tools=[],
        )
        assert result["ok"] is True
        assert result["output"] == "Hello from assistant"
        assert result["rounds"] == 1

    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-test")
    def test_max_iterations_reached(
        self, mock_model: MagicMock, mock_key: MagicMock, mock_client: MagicMock
    ) -> None:
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "some_tool"
        tc.function.arguments = "{}"
        msg = MagicMock()
        msg.content = ""
        msg.tool_calls = [tc]
        choice = MagicMock()
        choice.message = msg
        completion = MagicMock()
        completion.choices = [choice]
        mock_client.return_value.chat.completions.create.return_value = completion

        with patch(
            "app.application.tools.workflow.execute_workflow_tool", return_value='{"success": true}'
        ):
            result = run_employee_agent_loop(
                employee_id="emp1",
                system_prompt="test",
                task="loop",
                tools=[{"type": "function", "function": {"name": "some_tool"}}],
                max_iterations=2,
            )
        assert result["max_iterations_reached"] is True
        assert result["rounds"] == 2

    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-test")
    def test_gate_blocks_tool_call(
        self, mock_model: MagicMock, mock_key: MagicMock, mock_client: MagicMock
    ) -> None:
        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "dangerous_tool"
        tc.function.arguments = '{"action": "delete"}'
        msg1 = MagicMock()
        msg1.content = ""
        msg1.tool_calls = [tc]
        choice1 = MagicMock()
        choice1.message = msg1
        completion1 = MagicMock()
        completion1.choices = [choice1]

        msg2 = MagicMock()
        msg2.content = "Tool was blocked"
        msg2.tool_calls = None
        choice2 = MagicMock()
        choice2.message = msg2
        completion2 = MagicMock()
        completion2.choices = [choice2]

        mock_client.return_value.chat.completions.create.side_effect = [completion1, completion2]

        gate = MagicMock(return_value={"ok": False, "reason": "not allowed"})

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="blocked",
            tools=[{"type": "function", "function": {"name": "dangerous_tool"}}],
            gate=gate,
        )
        assert result["ok"] is True
        assert any(tc.get("blocked") for tc in result["tool_calls"])

    @patch("app.infrastructure.llm.client.get_openai_compatible_client")
    @patch("app.infrastructure.llm.client.require_api_key")
    @patch("app.infrastructure.llm.client.resolve_chat_model", return_value="gpt-test")
    def test_llm_call_failure_returns_error(
        self, mock_model: MagicMock, mock_key: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.return_value.chat.completions.create.side_effect = ConnectionError(
            "network down"
        )

        result = run_employee_agent_loop(
            employee_id="emp1",
            system_prompt="test",
            task="fail",
            tools=[],
        )
        assert result["ok"] is False
        assert "network down" in result["error"]
