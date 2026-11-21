"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


class TestHandleExcelAnalysisActions:
    """Cover handle_excel_analysis action branches."""

    def test_file_not_found_returns_error(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        result = handle_excel_analysis(
            {"file_path": "missing.xlsx", "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_unsupported_action(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        # Create a real xlsx file so we get past file checks.
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "weird_action"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]

    def test_action_read(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "read"
        assert result["row_count"] == 3
        assert "columns" in result
        assert "records" in result

    def test_action_read_with_header_row(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        # Two-row header scenario.
        pd.DataFrame({"unnamed": ["header_note", 1, 2], "a": ["A", 10, 20]}).to_excel(
            p, index=False
        )
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read", "header_row": 2},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result.get("header_row") == 2

    def test_action_query_with_expression(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3, 4], "b": [10, 20, 30, 40]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["row_count"] == 2

    def test_action_query_without_expression(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error_code"] == "missing_query_expression"
        assert "records" not in result

    def test_action_aggregate_with_group_by(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"category": ["A", "A", "B"], "amount": [10, 20, 30]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["category"],
                "metrics": [{"column": "amount", "op": "sum"}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "aggregate"
        assert result["row_count"] >= 2

    def test_action_aggregate_no_group_by(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"数量": range(1, 206), "金额": [2 * n for n in range(1, 206)]}).to_excel(
            p, index=False
        )
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": [],
                "metrics": [
                    {"column": "数量", "op": "sum"},
                    {"column": "金额", "op": "sum"},
                    {"column": "数量", "op": "count"},
                ],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["row_count"] == 1
        assert result["source_row_count"] == 205
        assert result["records"] == [{"数量_sum": 21115, "数量_count": 205, "金额_sum": 42230}]
        assert result["truncated"] is False

    def test_action_aggregate_invalid_metrics(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["a"],
                "metrics": ["not_a_dict", {"column": "", "op": ""}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is False

    def test_action_statistics(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "statistics"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result
        assert result["row_count"] == 3

    def test_query_expression_filters_rows(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "query",
                "query_expression": "a > 2",
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"a": 3}]

    def test_read_failure_returns_error(self, tmp_path: Path):
        from app.application.tools.workflow import handle_excel_analysis

        # Create a non-Excel file to force a read failure.
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
        assert "bad excel" not in result["error"]


class TestExecuteWorkflowToolStringArgs:
    """Cover execute_workflow_tool when args is a JSON string."""

    def test_string_args_valid_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", json.dumps({"file_path": "x.xlsx"}))
        parsed = json.loads(result)
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"

    def test_string_args_invalid_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", "not json")
        parsed = json.loads(result)
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"

    def test_excel_chart_recommend(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", {})
        parsed = json.loads(result)
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"
