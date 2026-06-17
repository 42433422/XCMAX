"""Tests for app.application.tools.workflow — deep coverage for remaining uncovered branches.

Focus: execute_workflow_tool, handle_excel_analysis edge cases, registry functions,
run_natural_language_pandas, and import excel to database branches.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# ========================= _parse_excel_header_row_1based - extended =======


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


# ========================= handle_excel_analysis - deep ====================


class TestHandleExcelAnalysisDeep:
    def test_no_file_path(self):
        from app.application.tools.workflow import handle_excel_analysis

        result = handle_excel_analysis({"action": "read"})
        assert result["success"] is False
        assert "file_path" in result["error"]

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
        assert "read failed" in result["error"]

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
        assert result["success"] is True

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

    def test_excel_query_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "nlq.xlsx")
        df.to_excel(xlsx_path, index=False)

        with (
            patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path(xlsx_path),
            ),
            patch("app.application.tools.workflow.run_natural_language_pandas") as mock_run,
        ):
            mock_run.return_value = {
                "generated_code": "",
                "result_kind": "dataframe",
                "row_count": 2,
                "records": [],
            }
            result = handle_excel_analysis(
                {
                    "file_path": xlsx_path,
                    "action": "excel_query",
                    "natural_language": "show all",
                }
            )
        assert result["action"] == "excel_query"

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
                "app.routes.template_grid_core._extract_customer_hint_from_excel",
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


# ========================= run_natural_language_pandas - extended ==========


class TestRunNaturalLanguagePandasExtended:
    def test_empty_code(self):
        import pandas as pd

        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        # ExcelTextToPandas doesn't exist as a module, so the import will fail
        # and the function will catch ImportError (in RECOVERABLE_ERRORS)
        result = run_natural_language_pandas(df, "show all")
        assert result["result_kind"] == "dataframe"
        # Since import fails, generated_code will be empty and error will be set
        assert result["generated_code"] == ""

    def test_exception_in_translation(self):
        import pandas as pd

        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        # The import of ExcelTextToPandas will fail, causing an error
        result = run_natural_language_pandas(df, "show all")
        # The function catches RECOVERABLE_ERRORS and sets error_msg
        assert "error" in result or result["generated_code"] == ""

    def test_successful_translation(self):
        import pandas as pd

        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        # Mock the ExcelTextToPandas import to simulate successful translation
        mock_converter = Mock()
        mock_converter.translate.return_value = "result = df[df['value'] > 1]"
        with patch.dict(
            "sys.modules",
            {
                "app.legacy.excel_text_to_pandas": Mock(
                    ExcelTextToPandas=Mock(return_value=mock_converter)
                )
            },
        ):
            result = run_natural_language_pandas(df, "value greater than 1")
        assert result["result_kind"] == "dataframe"
        assert result["row_count"] == 1


# ========================= get_workflow_tool_registry - extended ===========


class TestGetWorkflowToolRegistryExtended:
    def test_base_registry_count(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        assert (
            len(reg) >= 5
        )  # At least excel_analysis, excel_schema, excel_join, excel_chart, import_excel

    def test_registry_caching(self):
        from app.application.tools.workflow import (
            _workflow_tool_registry_cache,
            get_workflow_tool_registry,
        )

        # First call populates cache
        with patch("app.application.tools.workflow._workflow_tool_registry_cache", None):
            with patch("app.application.tools.workflow._workflow_registry_cache_ver", None):
                reg = get_workflow_tool_registry()
        assert isinstance(reg, list)

    def test_registry_with_bulk_token(self):
        from app.application.tools.workflow import get_workflow_tool_registry

        with patch.dict("os.environ", {"FHD_DB_WRITE_TOKEN": "test_token"}):
            with patch("app.application.tools.workflow._workflow_tool_registry_cache", None):
                with patch("app.application.tools.workflow._workflow_registry_cache_ver", None):
                    reg = get_workflow_tool_registry()
        tool_names = [t["function"]["name"] for t in reg]
        assert "products_bulk_import" in tool_names

    def test_invalidate_registry(self):
        from app.application.tools.workflow import invalidate_workflow_tool_registry

        with patch("app.application.tools.workflow._workflow_tool_registry_cache", [{"old": True}]):
            invalidate_workflow_tool_registry()
        from app.application.tools.workflow import _workflow_tool_registry_cache

        assert _workflow_tool_registry_cache is None


# ========================= execute_workflow_tool - extended ================


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
        assert "suggestions" in parsed

    def test_unknown_tool_returns_json(self):
        from app.application.tools.workflow import execute_workflow_tool

        # Most unknown tools fall through to the end
        with patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False):
            with patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ):
                with patch(
                    "app.application.employee_pack_runner.try_execute_employee_planner_tool",
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


# ========================= _base_registry - tool definitions ==============


class TestBaseRegistryToolDefinitions:
    def test_excel_analysis_tool(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "excel_analysis" in names

    def test_excel_schema_understand_tool(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "excel_schema_understand" in names

    def test_excel_join_compare_tool(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "excel_join_compare" in names

    def test_excel_chart_recommend_tool(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "excel_chart_recommend" in names

    def test_import_excel_to_database_tool(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "import_excel_to_database" in names

    def test_generate_office_document_tool(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "generate_office_document" in names
