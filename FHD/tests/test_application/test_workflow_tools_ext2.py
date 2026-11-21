"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestParseExcelHeaderRow1BasedExtended:
    def test_none_raw(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({})
        assert result is None

    def test_empty_string(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({"header_row": ""})
        assert result is None

    def test_fallback_to_header_row_index(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({"header_row": None, "header_row_index": 3})
        assert result == 3

    def test_invalid_value(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({"header_row": "abc"})
        assert result is None

    def test_zero_value(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({"header_row": 0})
        assert result is None

    def test_negative_value(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({"header_row": -1})
        assert result is None

    def test_valid_value(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({"header_row": 2})
        assert result == 2


class TestHandleExcelAnalysisDeep:
    def test_resolve_error(self):
        from app.application.tools.workflow import handle_excel_analysis

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=ValueError("bad path"),
        ):
            result = handle_excel_analysis({"file_path": "../etc/passwd", "action": "read"})
        assert result["success"] is False

    def test_file_not_found(self, tmp_path):
        from app.application.tools.workflow import handle_excel_analysis

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path("/nonexistent.xlsx"),
        ):
            result = handle_excel_analysis({"file_path": "nonexistent.xlsx", "action": "read"})
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_read_failed(self, tmp_path):
        from app.application.tools.workflow import handle_excel_analysis

        xlsx_path = str(tmp_path / "bad.xlsx")
        Path(xlsx_path).write_bytes(b"not an excel file")

        with (
            patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path(xlsx_path),
            ),
            patch(
                "app.application.tools.workflow._read_excel_dataframe",
                side_effect=ValueError("bad excel"),
            ),
        ):
            result = handle_excel_analysis({"file_path": xlsx_path, "action": "read"})
        assert result["success"] is False
        assert result["error"] == "read_excel_failed"
        assert "bad excel" not in result["error"]

    def test_read_pagination(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"a": list(range(300))})
        xlsx_path = str(tmp_path / "page.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            first = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "read", "max_rows": 200}
            )
            second = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "read", "max_rows": 200, "offset": 200}
            )
        assert first["row_count"] == 300
        assert first["returned_rows"] == 200
        assert first["has_more"] is True
        assert first["next_offset"] == 200
        assert second["returned_rows"] == 100
        assert second["has_more"] is False
        assert second["next_offset"] is None

    def test_read_env_cap(self, tmp_path, monkeypatch):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        monkeypatch.setenv("FHD_EXCEL_ANALYSIS_MAX_PAGE_ROWS", "500")
        df = pd.DataFrame({"a": list(range(600))})
        xlsx_path = str(tmp_path / "cap.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "read", "max_rows": 9999}
            )
        assert result["page_rows"] == 500
        assert result["returned_rows"] == 500
        assert result["has_more"] is True

    def test_unsupported_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "test.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis({"file_path": xlsx_path, "action": "unknown_action"})
        assert result["success"] is False
        assert "unsupported_action" in result["error"]

    def test_aggregate_action_with_metrics(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"category": ["A", "A", "B"], "value": [10, 20, 30]})
        xlsx_path = str(tmp_path / "agg.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis(
                {
                    "file_path": xlsx_path,
                    "action": "aggregate",
                    "group_by": ["category"],
                    "metrics": [{"column": "value", "op": "sum"}],
                }
            )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_aggregate_action_no_metrics(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"category": ["A", "B"], "value": [10, 20]})
        xlsx_path = str(tmp_path / "agg2.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis(
                {
                    "file_path": xlsx_path,
                    "action": "aggregate",
                    "group_by": [],
                    "metrics": [],
                }
            )
        assert result["success"] is False
        assert result["error"] == "missing_aggregation_metrics"

    def test_statistics_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "stats.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis({"file_path": xlsx_path, "action": "statistics"})
        assert result["success"] is True
        assert "dtypes" in result

    def test_query_action_with_expression(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "query.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis(
                {
                    "file_path": xlsx_path,
                    "action": "query",
                    "query_expression": "value > 1",
                }
            )
        assert result["success"] is True
        assert result["row_count"] == 1

    def test_query_expression_filters_rows(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "nlq.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {
                    "file_path": xlsx_path,
                    "action": "query",
                    "query_expression": "value > 1",
                }
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["records"] == [{"name": "B", "value": 2}]

    def test_read_with_customer_hint(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "hint.xlsx")
        df.to_excel(xlsx_path, index=False)

        with (
            patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path(xlsx_path),
            ),
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="测试公司",
            ),
        ):
            result = handle_excel_analysis({"file_path": xlsx_path, "action": "read"})
        assert result["success"] is True
        assert result.get("customer_hint") == "测试公司"

    def test_read_with_header_row(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "hdr.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "read", "header_row": 1}
            )
        assert result["success"] is True
        assert result["header_row"] == 1


class TestExecuteWorkflowToolExtended:
    def test_string_args_parsed(self):
        from app.application.tools.workflow import execute_workflow_tool

        with patch(
            "app.application.tools.workflow.handle_excel_analysis", return_value={"success": True}
        ):
            result = execute_workflow_tool(
                "excel_analysis", '{"file_path": "test.xlsx", "action": "read"}'
            )
        assert isinstance(result, str)

    def test_invalid_json_args(self):
        from app.application.tools.workflow import execute_workflow_tool

        with patch(
            "app.application.tools.workflow.handle_excel_analysis", return_value={"success": True}
        ):
            result = execute_workflow_tool("excel_analysis", "not json")
        assert isinstance(result, str)

    def test_excel_chart_recommend(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("excel_chart_recommend", {"file_path": "test.xlsx"})
        parsed = json.loads(result)
        assert parsed["error_code"] == "unknown_tool"
        assert parsed["execution_status"] == "not_started"

    def test_unknown_tool_returns_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        # Most unknown tools fall through to the end
        with patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False):
            with patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ):
                with patch(
                    "app.domain.app_pure.employee_pack_runner.try_execute_employee_planner_tool",
                    return_value=None,
                ):
                    result = execute_workflow_tool("unknown_tool", {})
        # Returns string (json)
        assert isinstance(result, str)

    def test_employee_tool_dispatch(self):
        from app.application.tools.workflow import execute_workflow_tool

        with patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=True):
            with patch(
                "app.mod_sdk.employee_tool_registry.execute_employee_tool",
                return_value='{"success": true}',
            ):
                result = execute_workflow_tool("employee_tool", {})
        assert isinstance(result, str)

    def test_native_planner_tool_dispatch(self):
        from app.application.tools.workflow import execute_workflow_tool

        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=('{"native": true}', None),
            ),
        ):
            result = execute_workflow_tool("native_tool", {})
        assert isinstance(result, str)
