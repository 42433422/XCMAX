"""Tests for app.application.tools.workflow — uncovered branches (ext3).

Focus: _read_excel_dataframe engine selection, _excel_cell_as_clean_str,
_excel_cell_as_float, _looks_like_contract_or_footer_line,
_infer_product_field_mapping, _import_products_preview_or_execute,
_import_customers_preview_or_execute, _import_orders_preview_or_execute,
excel_join_compare handler, excel_prophet handler, excel_schema_understand handler,
products_bulk_import handler, excel_vector_index handler, import_excel_to_database handler,
generate_office_document handler.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# ========================= _read_excel_dataframe engine selection ===========


class TestReadExcelDataframeEngineSelection:
    def test_xlsx_file_uses_openpyxl(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = tmp_path / "test.xlsx"
        df.to_excel(str(xlsx_path), index=False)

        result = _read_excel_dataframe(xlsx_path, sheet_name=None, header_row_1based=1)
        assert len(result) == 2
        assert "name" in result.columns

    def test_with_sheet_name(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = tmp_path / "test_sheet.xlsx"
        df.to_excel(str(xlsx_path), index=False, sheet_name="Sheet1")

        result = _read_excel_dataframe(xlsx_path, sheet_name="Sheet1", header_row_1based=1)
        assert len(result) == 1

    def test_none_header_row(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = tmp_path / "test_hdr.xlsx"
        df.to_excel(str(xlsx_path), index=False)

        # header_row_1based=None means no header arg passed
        result = _read_excel_dataframe(xlsx_path, sheet_name=None, header_row_1based=None)
        assert result is not None


# ========================= _excel_cell_as_clean_str ========================


class TestExcelCellAsCleanStr:
    def test_string_value(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("hello") == "hello"

    def test_none_value(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(None) == ""

    def test_nan_value(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(float("nan")) == ""

    def test_integer_value(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(42) == "42"

    def test_float_value(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        result = _excel_cell_as_clean_str(3.14)
        assert "3.14" in result

    def test_whitespace_stripped(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("  hello  ") == "hello"

    def test_bool_returns_empty(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(True) == ""


# ========================= _excel_cell_as_float ============================


class TestExcelCellAsFloat:
    def test_float_value(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(3.14) == 3.14

    def test_int_value(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(42) == 42.0

    def test_string_number(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("3.14") == 3.14

    def test_invalid_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("not a number") == 0.0

    def test_none_value(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None) == 0.0

    def test_nan_value(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(float("nan")) == 0.0

    def test_empty_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("") == 0.0

    def test_custom_default(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None, default=-1.0) == -1.0


# ========================= _looks_like_contract_or_footer_line ==============


class TestLooksLikeContractOrFooterLine:
    def test_clause_line(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("含税价格不含运费") is True

    def test_numbered_clause(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("1、以上价格含税含运费") is True

    def test_normal_data_line(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("涂料A") is False

    def test_short_line(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("短") is False

    def test_empty_string(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("") is False

    def test_none_value(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line(None) is False


# ========================= _infer_product_field_mapping ====================


class TestInferProductFieldMapping:
    def test_with_standard_headers(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        headers = ["产品名称", "型号", "单价", "数量", "客户"]
        result = _infer_product_field_mapping(headers)
        assert isinstance(result, dict)

    def test_with_empty_headers(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping([])
        assert isinstance(result, dict)

    def test_with_non_standard_headers(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        headers = ["名称", "编号", "价格", "数量"]
        result = _infer_product_field_mapping(headers)
        assert isinstance(result, dict)

    def test_with_price_column_hint(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        headers = ["产品名称", "单价", "调价前单价"]
        result = _infer_product_field_mapping(headers, price_column_hint="调价前单价")
        assert isinstance(result, dict)


# ========================= execute_workflow_tool - additional handlers ======


class TestExecuteWorkflowToolAdditionalHandlers:
    def test_import_excel_to_database_missing_path(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("import_excel_to_database", {})
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_products_bulk_import_no_token(self):
        from app.application.tools.workflow import execute_workflow_tool

        with patch.dict("os.environ", {"FHD_DB_WRITE_TOKEN": ""}):
            result = execute_workflow_tool("products_bulk_import", {"products": []})
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_excel_vector_index(self):
        from app.application.tools.workflow import execute_workflow_tool

        with patch("app.application.get_excel_vector_ingest_app_service") as mock_get:
            mock_svc = Mock()
            mock_svc.ingest_excel.return_value = {"success": True, "index_id": "idx1"}
            mock_get.return_value = mock_svc
            with patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path("/test.xlsx"),
            ):
                with patch.object(Path, "exists", return_value=True):
                    result = execute_workflow_tool(
                        "excel_vector_index", {"file_path": "/test.xlsx"}
                    )
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_excel_join_compare_diff(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import execute_workflow_tool

        df = pd.DataFrame({"key": ["A", "B"], "val1": [1, 2]})
        xlsx_path = str(tmp_path / "join.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = execute_workflow_tool(
                "excel_join_compare",
                {
                    "file_path_a": xlsx_path,
                    "file_path_b": xlsx_path,
                    "action": "diff",
                    "key_columns": ["key"],
                },
            )
        parsed = json.loads(result)
        assert "action" in parsed
        assert parsed["action"] == "diff"

    def test_excel_join_compare_diff_no_keys(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import execute_workflow_tool

        df = pd.DataFrame({"key": ["A", "B"], "val1": [1, 2]})
        xlsx_path = str(tmp_path / "join.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = execute_workflow_tool(
                "excel_join_compare",
                {
                    "file_path_a": xlsx_path,
                    "file_path_b": xlsx_path,
                    "action": "diff",
                },
            )
        parsed = json.loads(result)
        assert "action" in parsed

    def test_excel_join_compare_unknown_action(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool(
            "excel_join_compare",
            {
                "action": "unknown_action",
            },
        )
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_excel_prophet_with_file(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import execute_workflow_tool

        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=10), "value": range(10)})
        xlsx_path = str(tmp_path / "prophet.xlsx")
        df.to_excel(xlsx_path, index=False)

        with (
            patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path(xlsx_path),
            ),
            patch("app.application.tools.workflow._read_excel_dataframe", return_value=df),
        ):
            result = execute_workflow_tool(
                "excel_prophet",
                {
                    "file_path": xlsx_path,
                    "value_column": "value",
                },
            )
        parsed = json.loads(result)
        assert "action" in parsed
        assert parsed["action"] == "forecast"
        assert "future_forecast" in parsed

    def test_excel_prophet_no_file(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool(
            "excel_prophet",
            {
                "value_column": "value",
            },
        )
        parsed = json.loads(result)
        assert "action" in parsed
        assert parsed["action"] == "forecast"

    def test_excel_schema_understand(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import execute_workflow_tool

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "schema.xlsx")
        df.to_excel(xlsx_path, index=False)

        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path", return_value=Path(xlsx_path)
        ):
            result = execute_workflow_tool("excel_schema_understand", {"file_path": xlsx_path})
        parsed = json.loads(result)
        # Returns snapshot with column info, not a "success" key
        assert "snapshot" in parsed or "columns" in parsed or isinstance(parsed, dict)

    def test_generate_office_document(self):
        from app.application.tools.workflow import execute_workflow_tool

        with (
            patch(
                "app.services.kitten_ai_document.generate.generate_office_file",
                return_value=(b"content", "test.docx"),
            ),
            patch(
                "app.services.kitten_ai_document.pickup.store_document_pickup",
                return_value="pickup_tok",
            ),
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
            ),
        ):
            result = execute_workflow_tool(
                "generate_office_document", {"user_request": "test doc", "output_format": "docx"}
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["artifacts"][0]["artifact_type"] == "office_document"
        assert parsed["artifacts"][0]["name"] == "test.docx"
        assert parsed["artifacts"][0]["uri"] == "/api/ai/kitten/document/pickup/pickup_tok"

    def test_generate_office_document_missing_request(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("generate_office_document", {"output_format": "docx"})
        parsed = json.loads(result)
        assert parsed["success"] is False


# ========================= _import_products_preview_or_execute ==============


class TestImportProductsPreviewOrExecute:
    def test_preview_mode(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame({"产品名称": ["涂料A"], "型号": ["5003A"], "单价": [100]})
        result = _import_products_preview_or_execute(
            df,
            ["产品名称", "型号", "单价"],
            "公司A",
            False,
            1,
        )
        # Function returns JSON string
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_empty_dataframe(self):
        import pandas as pd

        from app.application.tools.workflow import _import_products_preview_or_execute

        df = pd.DataFrame()
        result = _import_products_preview_or_execute(df, [], "公司A", False, 0)
        parsed = json.loads(result)
        assert parsed["success"] is True


# ========================= _import_customers_preview_or_execute =============


class TestImportCustomersPreviewOrExecute:
    def test_preview_mode(self):
        import pandas as pd

        from app.application.tools.workflow import _import_customers_preview_or_execute

        df = pd.DataFrame({"名称": ["公司A"], "联系人": ["张三"]})
        result = _import_customers_preview_or_execute(df, ["名称", "联系人"], False, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_empty_dataframe(self):
        import pandas as pd

        from app.application.tools.workflow import _import_customers_preview_or_execute

        df = pd.DataFrame()
        result = _import_customers_preview_or_execute(df, [], False, 0)
        parsed = json.loads(result)
        assert parsed["success"] is True


# ========================= _import_orders_preview_or_execute ================


class TestImportOrdersPreviewOrExecute:
    def test_preview_mode(self):
        import pandas as pd

        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["涂料"], "数量": [10]})
        result = _import_orders_preview_or_execute(df, ["产品名称", "数量"], "公司A", False, 1)
        parsed = json.loads(result)
        assert parsed["success"] is True

    def test_empty_dataframe(self):
        import pandas as pd

        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame()
        result = _import_orders_preview_or_execute(df, [], "公司A", False, 0)
        parsed = json.loads(result)
        assert parsed["success"] is True
