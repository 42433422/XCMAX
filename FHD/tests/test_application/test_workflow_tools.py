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


def test_excel_query_reports_original_rows_after_filter_and_aggregation(tmp_path):
    from openpyxl import Workbook

    from app.application.tools.workflow import handle_excel_analysis
    from app.infrastructure.excel.pandas_translator import LLMPandasTranslator

    path = tmp_path / "sample.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "出货"
    for row in (["标题"], ["数量", "金额"], [3, 800], [1, 100], [4, 900]):
        sheet.append(row)
    workbook.save(path)
    args = {"action": "query", "file_path": str(path), "header_row": 2}
    with patch.object(
        LLMPandasTranslator,
        "translate",
        return_value=json.dumps(
            {
                "query_expression": "c0 > 2",
                "metrics": [{"column": "金额", "op": "sum"}],
            }
        ),
    ):
        result = handle_excel_analysis({**args, "question": "数量超过两件的金额合计"})
    assert result["success"], result
    assert result["sheet_name"] == "出货"
    assert result["records"] == [{"金额_sum": 1700}]
    assert result["source_rows"] == {
        "row_ranges": [[3, 3], [5, 5]],
        "row_ranges_truncated": False,
        "source_row_count": 2,
    }
