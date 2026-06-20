"""COVERAGE_RAMP Phase 1 (p1-p0-core): workflow tools + planner execute_tool (mocked)."""

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
from app.application.workflow.planner import execute_tool, get_tool_registry

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
# planner execute_tool (mocked services)
# ---------------------------------------------------------------------------


def test_get_tool_registry_keys() -> None:
    reg = get_tool_registry()
    assert isinstance(reg, dict)
    assert "products" in reg or "price_list" in reg


def test_execute_tool_unknown() -> None:
    out = execute_tool("nonexistent_tool_xyz", {})
    assert out["success"] is False


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("products", "query"): lambda p: {"success": True, "data": []}},
    clear=False,
)
def test_execute_tool_products() -> None:
    out = execute_tool("products", {"keyword": "x"})
    assert out["success"] is True


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("price_list", "export"): lambda p: {"success": False, "message": "no customer"}},
    clear=False,
)
def test_execute_tool_price_list() -> None:
    out = execute_tool("price_list", {})
    assert out["success"] is False


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("customers", "query"): lambda p: {"success": True}},
    clear=False,
)
def test_execute_tool_customers() -> None:
    out = execute_tool("customers", {"keyword": "甲"})
    assert out["success"] is True


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("shipment_generate", "generate"): lambda p: {"success": True}},
    clear=False,
)
def test_execute_tool_shipment_generate() -> None:
    out = execute_tool("shipment_generate", {"unit_name": "甲"})
    assert out["success"] is True


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("materials", "query"): lambda p: {"success": True, "data": []}},
    clear=False,
)
def test_execute_tool_materials() -> None:
    out = execute_tool("materials", {})
    assert out["success"] is True


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("print_label", "generate"): lambda p: {"success": True}},
    clear=False,
)
def test_execute_tool_print_label() -> None:
    out = execute_tool("print_label", {"template_id": "t1"})
    assert out["success"] is True


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("wechat_send", "preview"): lambda p: {"success": True}},
    clear=False,
)
def test_execute_tool_wechat_preview() -> None:
    out = execute_tool("wechat_send", {"contact": "Bob"})
    assert out["success"] is True


@patch.dict(
    "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
    {("import_excel", "import"): lambda p: {"success": True}},
    clear=False,
)
def test_execute_tool_import_excel() -> None:
    out = execute_tool("import_excel", {"file_path": "/tmp/a.xlsx"})
    assert out["success"] is True


def test_execute_price_list_missing_customer() -> None:
    from app.application.workflow.planner import _execute_price_list_tool

    out = _execute_price_list_tool({})
    assert out["success"] is False
    assert out["error_code"] == "missing_customer_name"


@patch("app.application.tools.handle_price_list_export")
@patch("app.application.workflow.planner.ensure_fhd_repo_on_syspath")
def test_execute_price_list_ok(mock_root: MagicMock, mock_export: MagicMock) -> None:
    from app.application.workflow.planner import _execute_price_list_tool

    mock_root.return_value = None
    mock_export.return_value = {"success": True, "file_path": "/tmp/p.xlsx"}
    out = _execute_price_list_tool({"customer_name": "甲公司"})
    assert out["success"] is True


@patch("app.bootstrap.get_products_service")
def test_execute_products_tool_query(mock_get: MagicMock) -> None:
    from app.application.workflow.planner import _execute_products_tool

    mock_get.return_value.get_products.return_value = {"success": True, "data": []}
    out = _execute_products_tool({"keyword": "x"})
    assert out["success"] is True


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
