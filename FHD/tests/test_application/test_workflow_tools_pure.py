"""Tests for app.application.tools.workflow — coverage ramp for pure functions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestParseExcelHeaderRow1Based:
    def test_valid_integer(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": 3}) == 3

    def test_string_integer(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": "5"}) == 5

    def test_zero_returns_none(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": 0}) is None

    def test_negative_returns_none(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": -1}) is None

    def test_empty_string(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": ""}) is None

    def test_none(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": None}) is None

    def test_missing_key(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({}) is None

    def test_fallback_to_header_row_index(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row_index": 4}) == 4

    def test_invalid_string(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        assert _parse_excel_header_row_1based({"header_row": "abc"}) is None


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

        assert _excel_cell_as_clean_str(3.0) == "3"

    def test_float_decimal(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(3.14) == "3.14"

    def test_nan_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("nan") == ""
        assert _excel_cell_as_clean_str("NaN") == ""

    def test_none_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("none") == ""

    def test_null_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("null") == ""

    def test_nat_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("NaT") == ""

    def test_normal_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("hello") == "hello"


class TestExcelCellAsFloat:
    def test_none(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None) == 0.0

    def test_nan_float(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(float("nan")) == 0.0

    def test_integer(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(42) == 42.0

    def test_string_number(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("3.14") == 3.14

    def test_invalid_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("abc") == 0.0

    def test_custom_default(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None, default=-1.0) == -1.0


class TestLooksLikeContractOrFooterLine:
    def test_short_text(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("短") is False

    def test_clause_substring(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("以上价格为含税价") is True

    def test_normal_name(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("环氧树脂E-44") is False

    def test_numbered_clause(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("1、以上各种产品均为合格产品") is True


class TestInferProductFieldMapping:
    def test_basic_columns(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["产品名称", "型号", "规格", "单价", "数量"])
        assert "name" in result
        assert "model_number" in result
        assert "specification" in result
        assert "price" in result
        assert "quantity" in result

    def test_empty_columns(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping([])
        assert result == {}

    def test_price_column_hint(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(
            ["调价前单价", "调价后单价"], price_column_hint="调价前"
        )
        assert "price" in result

    def test_model_number_variants(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["编号", "名称"])
        assert "model_number" in result

    def test_brand_and_category(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping(["品牌", "类别", "名称"])
        assert "brand" in result
        assert "category" in result


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
        assert "suggestions" in data

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


class TestBaseRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        assert isinstance(reg, list)
        assert len(reg) > 0

    def test_contains_excel_analysis(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "excel_analysis" in names

    def test_contains_import_excel(self):
        from app.application.tools.workflow import _base_registry

        reg = _base_registry()
        names = [t["function"]["name"] for t in reg]
        assert "import_excel_to_database" in names


class TestGetWorkflowToolRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import get_workflow_tool_registry

        reg = get_workflow_tool_registry()
        assert isinstance(reg, list)
        assert len(reg) > 0


class TestInvalidateWorkflowToolRegistry:
    def test_invalidate(self):
        from app.application.tools.workflow import (
            invalidate_workflow_tool_registry,
            get_workflow_tool_registry,
        )

        get_workflow_tool_registry()
        invalidate_workflow_tool_registry()
        # Should still work after invalidation
        reg = get_workflow_tool_registry()
        assert isinstance(reg, list)
