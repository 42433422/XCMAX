"""Workflow composition and the retained spreadsheet analysis contract."""

import json
import os
import tempfile
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestParseExcelHeaderRow1based:
    def test_valid_integer(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": 3}) == 3

    def test_string_integer(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": "5"}) == 5

    def test_header_row_index_fallback(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row_index": 2}) == 2

    def test_none(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": None}) is None

    def test_empty_string(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": ""}) is None

    def test_zero_rejected(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": 0}) is None

    def test_invalid_string(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": "abc"}) is None


class TestExecuteWorkflowTool:
    def test_unknown_tool(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("nonexistent_tool", {}))
        assert result["success"] is False
        assert "unknown_tool" in result.get("error", "")

    def test_excel_chart_recommend(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("excel_chart_recommend", {}))
        assert result["error_code"] == "unknown_tool"
        assert result["execution_status"] == "not_started"

    def test_excel_analysis_missing_path(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("excel_analysis", {"action": "read"}))
        assert result["success"] is False

    def test_generate_office_document_missing_request(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(
            execute_workflow_tool("generate_office_document", {"output_format": "docx"})
        )
        assert result["success"] is False

    def test_string_args_parsed(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("excel_chart_recommend", "{}"))
        assert result["error_code"] == "unknown_tool"
        assert result["execution_status"] == "not_started"

    def test_invalid_string_args(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("excel_chart_recommend", "not json"))
        assert result["error_code"] == "unknown_tool"
        assert result["execution_status"] == "not_started"


class TestHandleExcelAnalysis:
    def test_missing_file_path(self):
        from app.application.tools.workflow import handle_excel_analysis

        result = handle_excel_analysis({"action": "read"})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_unsupported_action(self):
        from app.application.tools.workflow import handle_excel_analysis

        with (
            patch("app.application.tools.workflow.resolve_safe_excel_path") as mock_resolve,
            patch("app.application.tools.workflow._read_excel_dataframe") as mock_read,
        ):
            from pathlib import Path

            mock_path = Mock(spec=Path)
            mock_path.exists.return_value = True
            mock_path.__str__ = lambda self: "/tmp/fake.xlsx"
            mock_resolve.return_value = mock_path
            mock_read.return_value = __import__("pandas").DataFrame({"a": [1]})
            result = handle_excel_analysis(
                {"file_path": "/tmp/fake.xlsx", "action": "unknown_action"}
            )
            assert result["success"] is False
            assert "unsupported_action" in result["error"]
