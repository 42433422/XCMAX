"""COVERAGE_RAMP Phase 1 (p1-p0-core): workflow helpers and registered dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.tools.workflow import (
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    invalidate_workflow_tool_registry,
)

# ---------------------------------------------------------------------------
# workflow.py pure helpers
# ---------------------------------------------------------------------------


def test_excel_cell_as_clean_str_variants() -> None:
    assert _excel_cell_as_clean_str(None) == ""
    assert _excel_cell_as_clean_str(float("nan")) == ""
    assert _excel_cell_as_clean_str(42.0) == "42"
    assert _excel_cell_as_clean_str("  hello  ") == "hello"
    assert _excel_cell_as_clean_str("nan") == ""


def test_excel_cell_as_float_variants() -> None:
    assert _excel_cell_as_float(None) == 0.0
    assert _excel_cell_as_float("3.5") == 3.5
    assert _excel_cell_as_float("bad", default=1.0) == 1.0


def test_looks_like_contract_or_footer_line() -> None:
    assert _looks_like_contract_or_footer_line("以上价格为含税价说明条款") is True
    assert _looks_like_contract_or_footer_line("短") is False
    assert _looks_like_contract_or_footer_line("普通产品名称ABC") is False


def test_infer_product_field_mapping() -> None:
    cols = ["产品名称", "规格", "数量", "单价", "金额"]
    mapping = _infer_product_field_mapping(cols)
    assert mapping.get("name") is not None or mapping.get("product_name") is not None


def test_workflow_tool_registry_roundtrip() -> None:
    invalidate_workflow_tool_registry()
    reg = get_workflow_tool_registry()
    assert isinstance(reg, list)
    assert len(reg) > 0
    names = set()
    for t in reg:
        if isinstance(t, dict):
            fn = t.get("function") or {}
            if isinstance(fn, dict) and fn.get("name"):
                names.add(fn["name"])
    assert len(names) > 0


def test_parse_excel_header_row_edge_cases() -> None:
    assert _parse_excel_header_row_1based({"header_row": -1}) is None
    assert _parse_excel_header_row_1based({"header_row": "2"}) == 2


# ---------------------------------------------------------------------------
# execute_workflow_tool entry (mocked)
# ---------------------------------------------------------------------------


@patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False)
@patch("app.application.tools.workflow._base_registry")
def test_execute_workflow_tool_unknown(mock_base: MagicMock, _mock_emp: MagicMock) -> None:
    mock_base.return_value = []
    out = execute_workflow_tool("unknown_xyz_tool", {})
    assert isinstance(out, str)
    assert "error" in out.lower() or "unknown" in out.lower() or "失败" in out
