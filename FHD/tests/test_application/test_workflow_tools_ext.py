"""Tests for app.application.tools.workflow — coverage ramp for uncovered branches."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# ========================= _read_excel_dataframe =========================


class TestReadExcelDataframe:
    def test_basic_read(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "test.xlsx")
        df.to_excel(xlsx_path, index=False)
        result = _read_excel_dataframe(Path(xlsx_path), sheet_name=None, header_row_1based=None)
        assert len(result) == 2

    def test_with_sheet_name(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "test_sheet.xlsx")
        df.to_excel(xlsx_path, sheet_name="Sheet1", index=False)
        result = _read_excel_dataframe(Path(xlsx_path), sheet_name="Sheet1", header_row_1based=None)
        assert len(result) == 1

    def test_with_header_row(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import _read_excel_dataframe

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        xlsx_path = str(tmp_path / "test_hdr.xlsx")
        df.to_excel(xlsx_path, index=False)
        result = _read_excel_dataframe(Path(xlsx_path), sheet_name=None, header_row_1based=1)
        assert isinstance(result, pd.DataFrame)


# ========================= handle_excel_analysis - extended ==============


class TestHandleExcelAnalysisExtended:
    def test_read_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "read_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "read"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_query_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "query_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "query", "query": "show all"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_statistics_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "stats_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "statistics"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_aggregate_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "A", "B"], "value": [1, 2, 3]})
        xlsx_path = str(tmp_path / "agg_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "aggregate"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_excel_query_action(self, tmp_path):
        import pandas as pd

        from app.application.tools.workflow import handle_excel_analysis

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        xlsx_path = str(tmp_path / "eq_test.xlsx")
        df.to_excel(xlsx_path, index=False)
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            return_value=Path(xlsx_path),
        ):
            result = handle_excel_analysis(
                {"file_path": xlsx_path, "action": "excel_query", "query": "show all"},
                workspace_root=str(tmp_path),
            )
        assert result["action"] == "excel_query"
        assert "result_kind" in result


# ========================= execute_workflow_tool - extended ===============


class TestExecuteWorkflowToolExtended:
    def test_excel_analysis_action(self, tmp_path):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(
            execute_workflow_tool(
                "excel_analysis",
                {"action": "read", "file_path": "/nonexistent/file.xlsx"},
            )
        )
        assert result["success"] is False

    def test_import_excel_no_token(self):
        from app.application.tools.workflow import execute_workflow_tool

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="required-token",
        ):
            result = json.loads(
                execute_workflow_tool(
                    "import_excel_to_database",
                    {"action": "products", "file_path": "/tmp/test.xlsx"},
                )
            )
        assert result["success"] is False

    def test_import_excel_with_token(self, monkeypatch):
        from app.application.tools.workflow import execute_workflow_tool

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="test-token",
        ):
            with patch(
                "app.application.tools.workflow._handle_import_excel_to_database",
                return_value=json.dumps({"success": True, "message": "ok"}),
            ):
                result = json.loads(
                    execute_workflow_tool(
                        "import_excel_to_database",
                        {
                            "action": "products",
                            "file_path": "/tmp/test.xlsx",
                            "db_write_token": "test-token",
                        },
                    )
                )
        assert isinstance(result, dict)

    def test_generate_office_document(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(
            execute_workflow_tool(
                "generate_office_document",
                {"output_format": "docx", "request": "test"},
            )
        )
        assert isinstance(result, dict)


# ========================= _handle_import_excel_to_database ===============


class TestHandleImportExcelToDatabase:
    def test_no_token(self):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="required-token",
        ):
            result = json.loads(
                _handle_import_excel_to_database(
                    {"action": "products", "file_path": "/tmp/test.xlsx"},
                    "/tmp",
                    "",
                )
            )
        assert result["success"] is False

    def test_products_action_missing_file(self, monkeypatch):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="test-token",
        ):
            with patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path("/nonexistent/file.xlsx"),
            ):
                result = json.loads(
                    _handle_import_excel_to_database(
                        {"action": "products", "file_path": "/nonexistent/file.xlsx"},
                        "/tmp",
                        "test-token",
                    )
                )
        assert result["success"] is False

    def test_customers_action_missing_file(self, monkeypatch):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="test-token",
        ):
            with patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path("/nonexistent/file.xlsx"),
            ):
                result = json.loads(
                    _handle_import_excel_to_database(
                        {"action": "customers", "file_path": "/nonexistent/file.xlsx"},
                        "/tmp",
                        "test-token",
                    )
                )
        assert result["success"] is False

    def test_orders_action_missing_file(self, monkeypatch):
        from app.application.tools.workflow import _handle_import_excel_to_database

        with patch(
            "app.application.tools.workflow.configured_db_write_token",
            return_value="test-token",
        ):
            with patch(
                "app.application.tools.workflow.resolve_safe_excel_path",
                return_value=Path("/nonexistent/file.xlsx"),
            ):
                result = json.loads(
                    _handle_import_excel_to_database(
                        {"action": "orders", "file_path": "/nonexistent/file.xlsx"},
                        "/tmp",
                        "test-token",
                    )
                )
        assert result["success"] is False


# ========================= _infer_product_field_mapping - extended ========


class TestInferProductFieldMappingExtended:
    def test_unit_column(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["产品名称", "单位"])
        assert "unit" in result

    def test_specification_column(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        # "规格型号" contains "规格" but also "号" — the function skips "规格+号" combo
        # Use just "规格" to get specification
        result = _infer_product_field_mapping(["产品名称", "规格"])
        assert "specification" in result

    def test_quantity_column(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["产品名称", "数量"])
        assert "quantity" in result

    def test_description_column(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["产品名称", "备注"])
        assert "description" in result

    def test_brand_column(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["产品名称", "品牌"])
        assert "brand" in result

    def test_category_column(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["产品名称", "类别"])
        assert "category" in result


# ========================= _looks_like_contract_or_footer_line - extended =


class TestLooksLikeContractOrFooterLineExtended:
    def test_long_contract_clause(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert (
            _looks_like_contract_or_footer_line("2、本合同自双方签字盖章之日起生效，有效期一年")
            is True
        )

    def test_clause_with_gaizhang(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        # "盖章" is in _CLAUSE_SUBSTRINGS
        assert _looks_like_contract_or_footer_line("供应方签名盖章确认后生效") is True

    def test_product_name(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("环氧树脂E-44") is False

    def test_short_text(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("短") is False


# ========================= run_natural_language_pandas - extended =========


class TestRunNaturalLanguagePandasExtended:
    def test_with_translation(self):
        import pandas as pd

        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        with patch(
            "app.application.tools.workflow.translate_natural_language_to_pandas",
            return_value="df[df['value'] > 0]",
            create=True,
        ):
            result = run_natural_language_pandas(df, "show values greater than 0")
        assert "result_kind" in result

    def test_error_in_execution(self):
        import pandas as pd

        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"name": ["A"], "value": [1]})
        # The function should handle errors gracefully
        result = run_natural_language_pandas(df, "invalid query that might fail")
        assert "result_kind" in result
