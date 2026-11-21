"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.tools.workflow import (
    _read_excel_dataframe,
    execute_workflow_tool,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
)


class TestHandleExcelAnalysis:
    """handle_excel_analysis 分支覆盖。"""

    def test_missing_file_path_returns_error(self) -> None:
        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_resolve_path_error_returns_error(self) -> None:
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=OSError("denied"),
        ):
            result = handle_excel_analysis({"file_path": "x.xlsx"})
        assert result["success"] is False
        assert result["error"] == "invalid_excel_path"
        assert "denied" not in result["error"]

    def test_file_not_found_returns_error(self, tmp_path: Path) -> None:
        result = handle_excel_analysis({"file_path": "missing.xlsx"}, workspace_root=str(tmp_path))
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_read_failed_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("read fail"),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is False
        assert result["error"] == "read_excel_failed"

    def test_action_query_uses_expression(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query", "query_expression": "a > 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"a": 2}]

    def test_action_read_with_customer_hint(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with (
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="客户A",
                create=True,
            ),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert result["customer_hint"] == "客户A"
        assert result["action"] == "read"

    def test_action_read_customer_hint_error_swallowed(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with (
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                side_effect=OSError("fail"),
                create=True,
            ),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert "customer_hint" not in result

    def test_action_read_with_header_row(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with (
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="",
                create=True,
            ),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read", "header_row": 2},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["header_row"] == 2

    def test_action_query_with_expr(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query", "query_expression": "a > 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["row_count"] == 2

    def test_action_query_without_expr(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2, 3]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df) as read:
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        assert result["error_code"] == "missing_query_expression"
        assert "records" not in result
        read.assert_not_called()

    def test_action_aggregate_with_metrics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"cat": ["a", "a", "b"], "val": [1, 2, 3]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {
                    "file_path": "data.xlsx",
                    "action": "aggregate",
                    "group_by": ["cat"],
                    "metrics": [{"column": "val", "op": "sum"}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_action_aggregate_with_invalid_metrics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"cat": ["a"], "val": [1]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {
                    "file_path": "data.xlsx",
                    "action": "aggregate",
                    "group_by": ["cat"],
                    "metrics": ["not a dict", {"column": "", "op": ""}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False

    def test_action_aggregate_no_group_by(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "aggregate"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False

    def test_action_statistics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2, 3]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "statistics"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_unsupported_action(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("app.application.tools.workflow._read_excel_dataframe", return_value=df):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "unknown"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]


class TestExecuteWorkflowToolMisc:
    """execute_workflow_tool 其它分支覆盖。"""

    def test_unknown_tool(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            result = execute_workflow_tool("totally_unknown", {})
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "unknown_tool"
        assert data["tool"] == "totally_unknown"

    def test_template_preview_empty_action_defaults_to_view(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
            patch(
                "app.application.tools.registered_capabilities.execute_registered_capability",
                return_value='{"result":"ok"}',
                create=True,
            ) as capability,
        ):
            result = execute_workflow_tool("template_preview", {"action": ""})
        assert capability.call_args.args[0]["action"] == "view"
        data = json.loads(result)
        assert "result" in data

    def test_employee_planner_tool_returned(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value='{"emp": true}',
                create=True,
            ),
        ):
            result = execute_workflow_tool("some_tool", {})
        assert "emp" in result

    def test_planner_native_tool_error_stops_dispatch(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                side_effect=ImportError("no planner"),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        data = json.loads(result)
        assert data["execution_state"] == "unknown"
        assert data["retryable"] is False

    def test_employee_planner_tool_error_stops_dispatch(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                side_effect=RuntimeError("fail"),
                create=True,
            ),
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        data = json.loads(result)
        assert data["execution_state"] == "unknown"
        assert data["retryable"] is False


class TestReadExcelDataframe:
    """_read_excel_dataframe 分支覆盖。"""

    def test_xlsx_uses_openpyxl_engine(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert mock_read.call_args.kwargs.get("engine") == "openpyxl"

    def test_xlsm_uses_openpyxl_engine(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsm"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert mock_read.call_args.kwargs.get("engine") == "openpyxl"

    def test_sheet_name_passed(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name="Sheet2", header_row_1based=None)
            assert mock_read.call_args.kwargs.get("sheet_name") == "Sheet2"

    def test_header_row_passed(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=3)
            assert mock_read.call_args.kwargs.get("header") == 2

    def test_no_extra_kwargs_for_xls(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xls"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert "engine" not in mock_read.call_args.kwargs
