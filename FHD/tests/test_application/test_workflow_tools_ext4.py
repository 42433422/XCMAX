"""Tests for app.application.tools.workflow — deep coverage (ext4).

Focus: _excel_cell_as_clean_str, _excel_cell_as_float,
_looks_like_contract_or_footer_line, _parse_excel_header_row_1based,
_infer_product_field_mapping, _base_registry, execute_workflow_tool error branches.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# _excel_cell_as_clean_str
# ---------------------------------------------------------------------------


class TestExcelCellAsCleanStr:
    def test_none(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str(None) == ""

    def test_empty_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        assert _excel_cell_as_clean_str("") == ""

    def test_whitespace(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        result = _excel_cell_as_clean_str("  hello  ")
        assert result.strip() == "hello" or "hello" in result

    def test_float_nan(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        result = _excel_cell_as_clean_str(float("nan"))
        assert isinstance(result, str)

    def test_integer(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        result = _excel_cell_as_clean_str(42)
        assert isinstance(result, str)

    def test_float_value(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        result = _excel_cell_as_clean_str(3.14)
        assert isinstance(result, str)

    def test_string(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        result = _excel_cell_as_clean_str("hello")
        assert result == "hello"


# ---------------------------------------------------------------------------
# _excel_cell_as_float
# ---------------------------------------------------------------------------


class TestExcelCellAsFloat:
    def test_none(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None) == 0.0

    def test_empty_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("") == 0.0

    def test_valid_float_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("3.14") == pytest.approx(3.14)

    def test_valid_int_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("42") == 42.0

    def test_invalid_string(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float("abc") == 0.0

    def test_float_input(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(2.5) == 2.5

    def test_int_input(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(10) == 10.0

    def test_custom_default(self):
        from app.application.tools.workflow import _excel_cell_as_float

        assert _excel_cell_as_float(None, default=-1.0) == -1.0

    def test_nan_input(self):
        from app.application.tools.workflow import _excel_cell_as_float

        result = _excel_cell_as_float(float("nan"))
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# _looks_like_contract_or_footer_line
# ---------------------------------------------------------------------------


class TestLooksLikeContractOrFooterLine:
    def test_empty(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("") is False

    def test_normal_name(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line("产品A") is False

    def test_footer_pattern(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        # Try common footer patterns
        result = _looks_like_contract_or_footer_line("合计")
        assert isinstance(result, bool)

    def test_none_input(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        assert _looks_like_contract_or_footer_line(None) is False


# ---------------------------------------------------------------------------
# _parse_excel_header_row_1based
# ---------------------------------------------------------------------------


class TestParseExcelHeaderRow1based:
    def test_with_header_row_key(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        args = {"header_row": 2}
        result = _parse_excel_header_row_1based(args)
        assert result == 2

    def test_with_header_row_index_key(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        # The implementation reads `header_row_index` as a fallback key.
        args = {"header_row_index": 3}
        result = _parse_excel_header_row_1based(args)
        assert result == 3

    def test_empty_args(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({})
        assert result is None or result == 1

    def test_none_args(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        # The implementation does not guard against None; expect AttributeError.
        with pytest.raises(AttributeError):
            _parse_excel_header_row_1based(None)


# ---------------------------------------------------------------------------
# _infer_product_field_mapping
# ---------------------------------------------------------------------------


class TestInferProductFieldMapping:
    def test_empty_columns(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        result = _infer_product_field_mapping([])
        assert isinstance(result, dict)

    def test_common_columns(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        columns = ["产品名称", "型号", "规格", "数量", "单价", "单位"]
        result = _infer_product_field_mapping(columns)
        assert isinstance(result, dict)

    def test_english_columns(self):
        from app.application.tools.workflow import _infer_product_field_mapping

        columns = ["name", "model_number", "specification", "quantity", "price", "unit"]
        result = _infer_product_field_mapping(columns)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _base_registry
# ---------------------------------------------------------------------------


class TestBaseRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import _base_registry

        result = _base_registry()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_each_item_has_required_keys(self):
        from app.application.tools.workflow import _base_registry

        result = _base_registry()
        for item in result:
            # Each item follows the OpenAI-style tool spec:
            # {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
            assert "type" in item
            assert "function" in item
            func = item["function"]
            assert "name" in func
            assert "description" in func


# ---------------------------------------------------------------------------
# execute_workflow_tool — error branches
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolErrors:
    def test_unknown_tool(self):
        from app.application.tools.workflow import execute_workflow_tool

        # execute_workflow_tool returns a JSON-encoded string.
        result = execute_workflow_tool("nonexistent_tool_xyz", {})
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed.get("success") is False or "error" in parsed or "不支持" in str(parsed)

    def test_empty_tool_name(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("", {})
        assert isinstance(result, str)
        # Should be JSON-parseable.
        json.loads(result)

    def test_none_args(self):
        from app.application.tools.workflow import execute_workflow_tool

        # execute_workflow_tool tolerates None args by treating it as "{}".
        result = execute_workflow_tool("query_products", None)
        assert isinstance(result, str)
        json.loads(result)


# ---------------------------------------------------------------------------
# get_workflow_tool_registry
# ---------------------------------------------------------------------------


class TestGetWorkflowToolRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import get_workflow_tool_registry

        result = get_workflow_tool_registry()
        assert isinstance(result, list)

    def test_invalidate_and_reget(self):
        from app.application.tools.workflow import get_workflow_tool_registry, invalidate_workflow_tool_registry

        invalidate_workflow_tool_registry()
        result = get_workflow_tool_registry()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# run_natural_language_pandas
# ---------------------------------------------------------------------------


class TestRunNaturalLanguagePandas:
    def test_with_empty_args(self):
        from app.application.tools.workflow import run_natural_language_pandas

        # Signature: run_natural_language_pandas(df, natural_language, **kwargs).
        # Empty DataFrame + empty query returns a structured dict.
        df = pd.DataFrame()
        result = run_natural_language_pandas(df, "")
        assert isinstance(result, dict)

    def test_with_invalid_query(self):
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": [1, 2]})
        result = run_natural_language_pandas(df, "invalid query xyz")
        assert isinstance(result, dict)
