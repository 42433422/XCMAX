"""COVERAGE_RAMP Phase 6 round 13: backend low-coverage modules.

Targets:
- ``app/application/ai_chat_app_service.py`` (81.0% line coverage, 230 uncovered lines)
- ``app/application/workflow/planner.py`` (77.0% line coverage, 151 uncovered lines)
- ``app/application/tools/workflow.py`` (82.1% line coverage, 121 uncovered lines)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO). The handler functions themselves are exercised through
real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, httpx errors)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd
import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.tools.workflow import (
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
)
from app.application.workflow.planning_graph_policy import filter_registry_for_profile
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    validate_plan_graph,
)
from app.services.tools_execution.registry import (
    get_workflow_tool_registry as get_tool_registry,
)
from tests.fixtures.planner_model import goal_review_response

# ===========================================================================
# 1. app/application/ai_chat_app_service.py
# ===========================================================================


# ===========================================================================
# 2. app/application/workflow/planner.py
# ===========================================================================


class TestGetToolRegistryPlanner:
    """Cover get_tool_registry from planner."""

    def test_returns_dict_with_tools(self) -> None:
        reg = get_tool_registry()
        assert isinstance(reg, dict)
        assert "products" in reg
        assert "customers" in reg
        assert "shipment_orders" in reg
        assert "shipment_records" in reg

    def test_tool_has_required_fields(self) -> None:
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "availability" in spec, f"{tool_id} missing availability"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


class TestFilterToolRegistryForProfile:
    """Cover filter_registry_for_profile."""

    def test_non_dict_actions_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": "not a dict",
            },
        }
        result = filter_registry_for_profile(reg, "normal")
        assert "tool_a" not in result

    def test_non_dict_action_meta_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": "not a dict"},
            },
        }
        result = filter_registry_for_profile(reg, "normal")
        assert "tool_a" not in result


# ===========================================================================
# 3. app/application/tools/workflow.py
# ===========================================================================


class TestParseExcelHeaderRow1based:
    """Cover _parse_excel_header_row_1based."""

    def test_with_header_row(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 3}) == 3

    def test_with_header_row_index(self) -> None:
        assert _parse_excel_header_row_1based({"header_row_index": 2}) == 2

    def test_header_row_takes_precedence(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 3, "header_row_index": 2}) == 3

    def test_none_value(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": None}) is None

    def test_empty_string(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": ""}) is None

    def test_invalid_string(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": "abc"}) is None

    def test_zero_returns_none(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 0}) is None

    def test_negative_returns_none(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": -1}) is None

    def test_missing_key(self) -> None:
        assert _parse_excel_header_row_1based({}) is None


class TestHandleExcelAnalysis:
    """Cover handle_excel_analysis branches."""

    def test_missing_file_path(self) -> None:
        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = handle_excel_analysis(
            {"file_path": "missing.xlsx", "action": "read"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_unsupported_action(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "weird"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]

    def test_action_read(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "read"
        assert result["row_count"] == 3

    def test_action_read_with_header_row(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"unnamed": ["header_note", 1, 2], "a": ["A", 10, 20]}).to_excel(
            p, index=False
        )
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read", "header_row": 2},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result.get("header_row") == 2

    def test_action_query_with_expression(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3, 4]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_query_without_expression(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error_code"] == "missing_query_expression"
        assert "records" not in result

    def test_action_aggregate_with_group_by(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"category": ["A", "A", "B"], "amount": [10, 20, 30]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "header_row": 1,
                "group_by": ["category"],
                "metrics": [{"column": "amount", "op": "sum"}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_action_aggregate_no_group_by(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "header_row": 1,
                "metrics": [{"column": "a", "op": "sum"}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["records"] == [{"a_sum": 3}]

    def test_action_aggregate_invalid_metrics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "header_row": 1,
                "group_by": ["a"],
                "metrics": ["not_a_dict", {"column": "", "op": ""}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is False
        assert result["error"] == "invalid_aggregation_metrics"

    def test_action_statistics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "statistics", "header_row": 1},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_query_expression_filters_rows(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"a": 3}]

    def test_read_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not an excel file")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=ValueError("bad excel"),
        ):
            result = handle_excel_analysis(
                {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
            )
            assert result["success"] is False
        assert result["error"] == "read_excel_failed"


class TestExecuteWorkflowTool:
    """Cover execute_workflow_tool dispatch."""

    def test_string_args_parsed(self) -> None:
        result = execute_workflow_tool("unknown", '{"x": 1}')
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_invalid_string_args(self) -> None:
        result = execute_workflow_tool("unknown", "not json")
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_unknown_tool(self) -> None:
        result = execute_workflow_tool("unknown_tool", {})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "unknown_tool"

    def test_excel_chart_recommend(self) -> None:
        result = execute_workflow_tool("excel_chart_recommend", {})
        parsed = json.loads(result)
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"

    def test_retired_excel_alias_is_not_started(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = execute_workflow_tool(
            "excel_analysis",
            {"file_path": str(p), "action": "read"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"


@pytest.mark.parametrize(
    "message",
    [
        "你好",
        "查询产品",
        "",
        None,
        "hello there",
        "hi",
        "x" * 200,
        "导入",
        "导入Excel",
        "导入到数据库",
        "写入数据库",
        "帮我导入数据",
        "说明表格",
        "普通消息",
    ],
)
def test_unified_public_chat_never_turns_model_failure_or_import_words_into_success(
    message,
):
    from tests.test_application.ai_chat_test_helpers import _make_svc

    svc = _make_svc()
    with (
        patch.object(svc, "_persist_chat_turn"),
        patch.object(svc, "_persist_recallable_chat_turn"),
        patch(
            "app.application.ai_chat.dialogue_memory.prepare_chat_turn",
            return_value=None,
        ),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
        patch(
            "app.application.agent_runtime.gateway.run_runtime_task",
            return_value={
                "ok": False,
                "business_completed": False,
                "verified_operations": False,
                "execution_state": "failed",
                "exit_status": "planning_unavailable",
                "error_code": "planning_unavailable",
                "error": "模型未返回可验证的任务目标",
            },
        ) as runtime,
    ):
        result = svc.process_chat("u1", message, source="pro")
    assert result["success"] is False
    assert not result.get("toolCall")
    assert not hasattr(svc, "workflow_planner")
    assert not hasattr(svc, "_pending_workflows")
    if message:
        runtime.assert_called_once()
        assert runtime.call_args.kwargs["task"] == message
        assert runtime.call_args.kwargs["completion_mode"] == "auto"
        assert result["execution_state"] == "failed"
        assert result["business_completed"] is False
        assert result["data"]["error_code"] == "planning_unavailable"
    else:
        runtime.assert_not_called()
