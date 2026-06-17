"""COVERAGE_RAMP Phase 3 round 3: legacy_chat_adapter helpers, planner plan paths."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.application.workflow.legacy_chat_adapter import (
    _parse_generate_office_format,
    _planner_tools_max_workers,
    _post_tool_round_hint,
    _slow_tool_wait_message,
    _tool_key,
    _tool_stream_call_label,
    reset_planner_tool_dedup_state,
)
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
from app.application.workflow.types import PlanGraph


def test_tool_key_and_labels() -> None:
    assert _tool_key("excel_analysis", '{"a":1}') == _tool_key("excel_analysis", '{"a":1}')
    assert "Word" in _tool_stream_call_label("generate_office_document", '{"output_format":"docx"}')
    assert _slow_tool_wait_message("import_excel_to_database", "{}") is not None


def test_parse_generate_office_format() -> None:
    assert _parse_generate_office_format('{"output_format":"docx"}') == "docx"
    assert _parse_generate_office_format("not-json") == ""


def test_post_tool_round_hint_docx_success() -> None:
    tc = SimpleNamespace(
        function=SimpleNamespace(
            name="generate_office_document",
            arguments='{"output_format":"docx"}',
        )
    )
    hint = _post_tool_round_hint(
        [tc],
        [{"success": True, "download_url": "http://x/a.docx"}],
    )
    assert "Word" in hint


def test_planner_tools_max_workers_positive() -> None:
    assert _planner_tools_max_workers() >= 1


def test_reset_planner_tool_dedup_state() -> None:
    reset_planner_tool_dedup_state()


def test_fallback_plan_generic_query_node() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("gid", "查库存5003", get_tool_registry())
    assert isinstance(plan, PlanGraph)
    assert plan.nodes[0].tool_id in ("products", "customers")


@patch("app.application.workflow.planner.get_ai_conversation_service")
@patch("app.application.get_user_memory_rag_app_service")
def test_planner_plan_uses_fallback_when_react_none(
    mock_rag_get: MagicMock, mock_ai: MagicMock
) -> None:
    mock_rag_get.return_value.query.return_value = {"hits": []}
    planner = LLMWorkflowPlanner()
    with patch.object(planner, "_plan_with_react_multiagent", return_value=None):
        plan = planner.plan("u1", "查询产品5003", get_tool_registry(), {})
    assert plan.intent
    assert plan.nodes


@patch("app.application.workflow.legacy_chat_adapter.get_openai_compatible_client")
@patch("app.application.workflow.legacy_chat_adapter.require_api_key")
@patch("app.application.workflow.legacy_chat_adapter._get_workflow_tool_registry")
def test_legacy_chat_adapter_chat_minimal(
    mock_reg: MagicMock, _mock_key: MagicMock, mock_client: MagicMock
) -> None:
    mock_reg.return_value = []
    msg = MagicMock()
    msg.content = "好的"
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    mock_client.return_value.chat.completions.create.return_value = MagicMock(choices=[choice])
    from app.application.workflow.legacy_chat_adapter import chat

    out = chat("你好", workspace_root="/tmp", model="deepseek-chat")
    assert out is not None
