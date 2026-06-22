"""COVERAGE_RAMP Phase 4 round 29: normal_chat_dispatch slot routing + response builders."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from app.application.normal_chat_dispatch import (
    build_customers_query_response_dict,
    build_inventory_alert_response_dict,
    build_label_print_response_dict,
    build_product_query_response_dict,
    resolve_tool_execution_profile,
    route_normal_mode_message,
    run_normal_slot_product_query_from_message,
    run_normal_slot_shipment_preview,
    run_workflow_products_query_normal_profile,
)

# ---------------------------------------------------------------------------
# route_normal_mode_message
# ---------------------------------------------------------------------------


def test_route_shipment_number_style_order() -> None:
    rr = route_normal_mode_message("2桶5003A规格25")
    assert rr["intent"] == "shipment"
    assert rr["slots"]["number_style_order"] is True


def test_route_customers_query_with_keyword() -> None:
    rr = route_normal_mode_message("查询甲公司的客户")
    assert rr["intent"] == "customers_query"
    assert "甲公司" in str(rr["slots"].get("keyword", ""))


def test_route_inventory_alert() -> None:
    rr = route_normal_mode_message("原材料库存不足有哪些")
    assert rr["intent"] == "inventory_alert"


def test_route_label_print_slots() -> None:
    rr = route_normal_mode_message("贴标 ABCDEF 5张")
    assert rr["intent"] == "label_print"
    assert rr["slots"]["model_number"] == "ABCDEF"
    assert rr["slots"]["quantity"] == 5


def test_route_product_query_unit_model() -> None:
    rr = route_normal_mode_message("查一下甲公司的5003A")
    assert rr["intent"] == "product_query"
    assert rr["slots"].get("unit_name")
    assert rr["slots"].get("model_number") == "5003A"


def test_route_unknown_greeting() -> None:
    assert route_normal_mode_message("你好呀")["intent"] == "unknown"


# ---------------------------------------------------------------------------
# resolve_tool_execution_profile
# ---------------------------------------------------------------------------


def test_resolve_tool_execution_profile_variants() -> None:
    assert resolve_tool_execution_profile({"tool_execution_profile": "normal"}) == "normal"
    assert resolve_tool_execution_profile({"tool_execution_profile": "pro"}) == "pro_default"
    assert (
        resolve_tool_execution_profile({"ui_surface": "normal", "intent_channel": "pro"})
        == "normal"
    )
    assert resolve_tool_execution_profile({}) == "pro_default"


# ---------------------------------------------------------------------------
# build_* response dicts
# ---------------------------------------------------------------------------


@patch("app.bootstrap.get_products_service")
def test_build_product_query_response_dict(mock_get: MagicMock) -> None:
    mock_get.return_value.get_products.return_value = {
        "success": True,
        "data": [{"model_number": "5003A", "name": "清漆", "price": 120}],
    }
    rr = route_normal_mode_message("查5003A")
    body = build_product_query_response_dict(rr)
    assert body is not None
    assert body["autoAction"]["type"] == "show_products_float"
    assert "5003" in body["response"]


def test_build_product_query_wrong_intent() -> None:
    assert build_product_query_response_dict({"intent": "shipment"}) is None


def test_build_customers_query_response_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cls = MagicMock()
    mock_cls.return_value.search.return_value = [
        {"customer_name": "甲公司", "contact_person": "张三"}
    ]
    fake_mod = types.ModuleType("app.services.customers_service")
    fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)
    rr = route_normal_mode_message("查甲公司客户")
    body = build_customers_query_response_dict(rr)
    assert body is not None
    assert body["success"] is True
    assert "甲公司" in body["response"]


@patch("app.application.get_material_application_service")
def test_build_inventory_alert_response_dict(mock_get: MagicMock) -> None:
    mock_get.return_value.get_low_stock_materials.return_value = {
        "data": [{"name": "树脂", "quantity": 2, "unit": "kg"}],
    }
    rr = route_normal_mode_message("库存预警")
    body = build_inventory_alert_response_dict(rr)
    assert body is not None
    assert "低库存" in body["response"]


@patch("app.application.print_app_service.get_print_application_service")
def test_build_label_print_response_dict_success(mock_get: MagicMock) -> None:
    mock_get.return_value.print_single_label.return_value = {"success": True}
    rr = route_normal_mode_message("打标签 XQ88 2张")
    body = build_label_print_response_dict(rr)
    assert body is not None
    assert body["success"] is True
    assert "XQ88" in body["response"]


def test_build_label_print_missing_model() -> None:
    body = build_label_print_response_dict(
        {"intent": "label_print", "slots": {"model_number": "", "quantity": 1}}
    )
    assert body is not None
    assert body["success"] is False


# ---------------------------------------------------------------------------
# run_* helpers
# ---------------------------------------------------------------------------


@patch("app.application.normal_chat_dispatch.build_product_query_response_dict")
def test_run_normal_slot_product_query_miss(mock_build: MagicMock) -> None:
    mock_build.return_value = None
    out = run_normal_slot_product_query_from_message("随便聊聊")
    assert out["success"] is False


@patch("app.application.facades.tools_facade._parse_order_text")
def test_run_normal_slot_shipment_preview_parse_fail(mock_parse: MagicMock) -> None:
    mock_parse.return_value = {"success": False, "message": "缺单位"}
    out = run_normal_slot_shipment_preview("开单")
    assert out["success"] is True
    assert "缺单位" in out["response"]


def test_run_normal_slot_shipment_preview_empty() -> None:
    out = run_normal_slot_shipment_preview("  ")
    assert out["success"] is False


@patch("app.bootstrap.get_products_service")
def test_run_workflow_products_query_normal_profile(mock_get: MagicMock) -> None:
    mock_get.return_value.get_products.return_value = {
        "success": True,
        "data": [{"model_number": "X1"}],
    }
    out = run_workflow_products_query_normal_profile("查X1型号", {"keyword": "X1"})
    assert out["success"] is True
    assert out["normal_tool_profile"] is True
