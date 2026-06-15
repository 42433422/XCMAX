"""Tests for app.application.tools.workflow — coverage ramp."""

import json
import os
import tempfile
from unittest.mock import MagicMock, Mock, patch

import pytest


# ========================= _parse_excel_header_row_1based ================


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


# ========================= _infer_product_field_mapping ==================


class TestInferProductFieldMapping:
    def test_basic_mapping(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        columns = ["产品名称", "型号", "单价", "数量", "单位"]
        mapping = _infer_product_field_mapping(columns)
        assert "name" in mapping
        assert mapping["name"] == "产品名称"
        assert "model_number" in mapping
        assert "price" in mapping
        assert "quantity" in mapping
        assert "unit" in mapping

    def test_price_column_hint(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        columns = ["调价前含税单价", "调价后含税单价", "产品名称"]
        mapping = _infer_product_field_mapping(columns, price_column_hint="调价前")
        assert "price" in mapping
        assert "调价前" in mapping["price"]

    def test_empty_columns(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        mapping = _infer_product_field_mapping([])
        assert isinstance(mapping, dict)


# ========================= _excel_cell_as_clean_str =====================


class TestExcelCellAsCleanStr:
    def test_none(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(None) == ""

    def test_bool(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(True) == ""

    def test_integer(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(42) == "42"

    def test_float_integer(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(10.0) == "10"

    def test_float_decimal(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(10.5) == "10.5"

    def test_nan_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("nan") == ""

    def test_normal_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("hello") == "hello"


# ========================= _excel_cell_as_float ==========================


class TestExcelCellAsFloat:
    def test_none(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None) == 0.0

    def test_float(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(10.5) == 10.5

    def test_string_number(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("100") == 100.0

    def test_invalid_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("abc") == 0.0

    def test_nan(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(float("nan")) == 0.0


# ========================= _looks_like_contract_or_footer_line ===========


class TestLooksLikeContractOrFooterLine:
    def test_clause_substring(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("以上价格为含税价") is True

    def test_numbered_clause(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("1、若贵司未能按时付款") is True

    def test_short_text(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("产品") is False

    def test_normal_product(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("高级涂料 5003A") is False


# ========================= _base_registry ================================


class TestBaseRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        assert isinstance(reg, list)
        assert len(reg) > 0

    def test_has_excel_analysis(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [r["function"]["name"] for r in reg]
        assert "excel_analysis" in names

    def test_has_import_excel(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [r["function"]["name"] for r in reg]
        assert "import_excel_to_database" in names


# ========================= get_workflow_tool_registry ====================


class TestGetWorkflowToolRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import get_workflow_tool_registry

        reg = get_workflow_tool_registry()
        assert isinstance(reg, list)

    def test_caching(self):
        from app.application.tools.workflow import get_workflow_tool_registry

        reg1 = get_workflow_tool_registry()
        reg2 = get_workflow_tool_registry()
        assert reg1 is reg2

    def test_bulk_import_with_token(self, monkeypatch):
        from app.application.tools.workflow import (
            get_workflow_tool_registry,
            _workflow_tool_registry_cache,
        )

        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "test-token")
        # Clear cache
        import app.application.tools.workflow as mod

        mod._workflow_tool_registry_cache = None
        reg = get_workflow_tool_registry()
        names = [r["function"]["name"] for r in reg]
        assert "products_bulk_import" in names
        # Cleanup
        monkeypatch.delenv("FHD_DB_WRITE_TOKEN", raising=False)
        mod._workflow_tool_registry_cache = None


# ========================= invalidate_workflow_tool_registry =============


class TestInvalidateWorkflowToolRegistry:
    def test_invalidate_clears_cache(self):
        from app.application.tools.workflow import (
            invalidate_workflow_tool_registry,
            get_workflow_tool_registry,
            _workflow_tool_registry_cache,
        )
        import app.application.tools.workflow as mod

        get_workflow_tool_registry()  # populate cache
        invalidate_workflow_tool_registry()
        assert mod._workflow_tool_registry_cache is None


# ========================= execute_workflow_tool =========================


class TestExecuteWorkflowTool:
    def test_unknown_tool(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("nonexistent_tool", {}))
        assert result["success"] is False
        assert "unknown_tool" in result.get("error", "")

    def test_excel_chart_recommend(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("excel_chart_recommend", {}))
        assert "suggestions" in result

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
        assert "suggestions" in result

    def test_invalid_string_args(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = json.loads(execute_workflow_tool("excel_chart_recommend", "not json"))
        assert "suggestions" in result


# ========================= handle_excel_analysis =========================


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


# ========================= run_natural_language_pandas ===================


class TestRunNaturalLanguagePandas:
    def test_basic_query_no_translation(self):
        import pandas as pd
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"name": ["A", "B"], "value": [1, 2]})
        # app.legacy.excel_text_to_pandas may not exist; function falls back gracefully
        result = run_natural_language_pandas(df, "show all")
        assert result["result_kind"] == "dataframe"
        assert result["row_count"] == 2

    def test_empty_dataframe(self):
        import pandas as pd
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": []})
        result = run_natural_language_pandas(df, "show all")
        assert result["row_count"] == 0

    def test_translation_error_graceful(self):
        import pandas as pd
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": [1]})
        # If the legacy module doesn't exist, the function still returns a valid result
        result = run_natural_language_pandas(df, "show all")
        assert "result_kind" in result
