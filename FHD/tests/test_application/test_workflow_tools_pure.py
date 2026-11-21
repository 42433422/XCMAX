"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestParseExcelHeaderRow1Based:
    def test_negative_returns_none(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": -1}) is None

    def test_missing_key(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({}) is None

    def test_fallback_to_header_row_index(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row_index": 4}) == 4


class TestHandleExcelAnalysis:
    def test_missing_file_path(self):
        from app.application.tools.workflow import handle_excel_analysis

        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]


class TestExecuteWorkflowTool:
    def test_unknown_tool(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("unknown_tool_xyz", {})
        data = json.loads(result)
        assert data["success"] is False
        assert data.get("error") == "unknown_tool"

    def test_excel_chart_recommend(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", {"file_path": "test.xlsx"})
        data = json.loads(result)
        assert data["error_code"] == "unknown_tool"
        assert data["execution_status"] == "not_started"

    def test_args_as_string(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("unknown_tool", '{"key": "val"}')
        data = json.loads(result)
        assert data["success"] is False

    def test_args_invalid_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("unknown_tool", "not json{{{")
        data = json.loads(result)
        assert data["success"] is False
