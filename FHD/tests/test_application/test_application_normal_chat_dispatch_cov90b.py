"""Cov90b second-wave behavior tests for normal_chat_dispatch.

Targets previously-uncovered branches: tail-model fallback + token reject
(99/110-114), keyword combo build (120/125-127/131), product-query preview
RECOVERABLE_ERRORS fallback + query_desc bits (181-188), run_workflow no-kw
fallback + except (233/259-261), shipment-preview success path (304-312),
product-query success wrapper (325-326), wrong-intent guards (332/368/401),
customers non-list coercion (340), and the RECOVERABLE_ERRORS except branches
of every response builder (355-357/388-390/430-432).
"""

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
    route_normal_mode_message,
    run_normal_slot_product_query_from_message,
    run_normal_slot_shipment_preview,
    run_workflow_products_query_normal_profile,
)

# ---------------------------------------------------------------------------
# route_normal_mode_message — tail-model fallback & keyword combo build
# ---------------------------------------------------------------------------


def test_route_tail_model_fallback_sets_model_and_keyword() -> None:
    # "查 ABCDEF": query keyword + space-delimited token -> tail-model fallback
    # (lines 110-114) sets model_number; no Chinese combo so keyword == model
    # (line 131 else branch).
    rr = route_normal_mode_message("查 ABCDEF")
    assert rr["intent"] == "product_query"
    assert rr["slots"]["model_number"] == "ABCDEF"
    assert rr["slots"]["keyword"] == "ABCDEF"


def test_route_tail_model_token_rejected_falls_to_keyword() -> None:
    # "查 HTTP": tail token HTTP is rejected by the (API|HTTP|JSON|XML) guard
    # (line 113), so model_number is never set and we fall through to the
    # lowercase keyword fallback (line 133+).
    rr = route_normal_mode_message("查 HTTP")
    assert rr["intent"] == "product_query"
    assert "model_number" not in rr["slots"]
    assert rr["slots"]["keyword"] == "http"


def test_route_model_signal_with_combo_keyword() -> None:
    # "查询 型号:NX 树脂9803": model signal sets model_number=NX (line 97-99,
    # no unit_model), then the elif/model_number keyword path finds a
    # Chinese+code combo in the tail (lines 120,125-127).
    rr = route_normal_mode_message("查询 型号:NX 树脂9803")
    assert rr["intent"] == "product_query"
    assert rr["slots"]["model_number"] == "NX"
    assert rr["slots"]["keyword"] == "树脂9803"


# ---------------------------------------------------------------------------
# build_product_query_response_dict — query_desc bits & preview except
# ---------------------------------------------------------------------------


@patch("app.bootstrap.get_products_service")
def test_build_product_query_unit_and_model_desc_bits(mock_get: MagicMock) -> None:
    # unit_name + model_number + distinct keyword exercise all query_desc_bits
    # branches (lines 186, 188) plus the preview rendering path.
    mock_get.return_value.get_products.return_value = {
        "success": True,
        "data": [{"model_number": "5003A", "name": "清漆", "price": 99.5}],
    }
    route_result = {
        "intent": "product_query",
        "slots": {"unit_name": "甲公司", "model_number": "5003A", "keyword": "甲公司5003A"},
    }
    body = build_product_query_response_dict(route_result)
    assert body is not None
    assert body["autoAction"]["query"] == "甲公司5003A"
    # preview rendered a hit line with formatted money
    assert "预览命中 1 条" in body["response"]
    assert "￥99.50" in body["response"]


@patch("app.bootstrap.get_products_service")
def test_build_product_query_preview_recoverable_error(mock_get: MagicMock) -> None:
    # get_products raises a RECOVERABLE_ERRORS member -> preview swallowed
    # (lines 181-182), but the response dict is still returned with no preview
    # suffix.
    mock_get.return_value.get_products.side_effect = RuntimeError("db down")
    route_result = {"intent": "product_query", "slots": {"keyword": "油漆"}}
    body = build_product_query_response_dict(route_result)
    assert body is not None
    assert body["success"] is True
    assert "预览命中" not in body["response"]
    assert body["autoAction"]["query"] == "油漆"


# ---------------------------------------------------------------------------
# run_workflow_products_query_normal_profile — no-kw fallback & except
# ---------------------------------------------------------------------------


@patch("app.bootstrap.get_products_service")
def test_run_workflow_no_kw_uses_node_params_fallback(mock_get: MagicMock) -> None:
    # An "unknown" message yields no route keyword, so kw_preview falls back to
    # node_params (line 233). Assert the fallback keyword reaches get_products.
    mock_get.return_value.get_products.return_value = {
        "success": True,
        "data": [{"model_number": "Z9"}],
    }
    out = run_workflow_products_query_normal_profile("你好啊", {"keyword": "Z9"})
    assert out["success"] is True
    assert out["data"] == [{"model_number": "Z9"}]
    _, kwargs = mock_get.return_value.get_products.call_args
    assert kwargs["keyword"] == "Z9"


@patch("app.bootstrap.get_products_service")
def test_run_workflow_products_query_recoverable_error(mock_get: MagicMock) -> None:
    # get_products raises -> except branch returns failure envelope (259-261).
    mock_get.return_value.get_products.side_effect = ValueError("boom")
    out = run_workflow_products_query_normal_profile("查X1", {"keyword": "X1"})
    assert out["success"] is False
    assert out["data"] == []
    assert out["normal_tool_profile"] is True
    assert "boom" in out["message"]


# ---------------------------------------------------------------------------
# run_normal_slot_shipment_preview — success path
# ---------------------------------------------------------------------------


@patch("app.application.facades.tools_facade._parse_order_text")
def test_run_normal_slot_shipment_preview_success(mock_parse: MagicMock) -> None:
    # Successful parse drives the real build_shipment_preview_response_dict and
    # the normal_slot_dispatch flag stamping (lines 304-312).
    mock_parse.return_value = {
        "success": True,
        "unit_name": "甲公司",
        "products": [{"model_number": "5003A", "quantity": 2}],
    }
    out = run_normal_slot_shipment_preview("甲公司 2桶5003A规格25")
    assert out["success"] is True
    assert out["normal_slot_dispatch"] is True
    assert out["data"]["intent"] == "shipment_preview"
    assert out["task"]["payload"]["params"]["unit_name"] == "甲公司"


# ---------------------------------------------------------------------------
# run_normal_slot_product_query_from_message — success wrapper
# ---------------------------------------------------------------------------


@patch("app.bootstrap.get_products_service")
def test_run_normal_slot_product_query_success(mock_get: MagicMock) -> None:
    # A real product_query message produces a body, which gets the
    # normal_slot_dispatch flag stamped (lines 325-326).
    mock_get.return_value.get_products.return_value = {"success": True, "data": []}
    out = run_normal_slot_product_query_from_message("查5003A")
    assert out["success"] is True
    assert out["normal_slot_dispatch"] is True
    assert out["autoAction"]["type"] == "show_products_float"


# ---------------------------------------------------------------------------
# wrong-intent guards return None
# ---------------------------------------------------------------------------


def test_build_customers_query_wrong_intent_none() -> None:
    assert build_customers_query_response_dict({"intent": "product_query"}) is None


def test_build_inventory_alert_wrong_intent_none() -> None:
    assert build_inventory_alert_response_dict({"intent": "shipment"}) is None


def test_build_label_print_wrong_intent_none() -> None:
    assert build_label_print_response_dict({"intent": "product_query"}) is None


# ---------------------------------------------------------------------------
# build_customers_query_response_dict — non-list coercion & except
# ---------------------------------------------------------------------------


def test_build_customers_query_non_list_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    # svc.search returns a non-list -> coerced to [] (line 340) -> "未找到" msg.
    mock_cls = MagicMock()
    mock_cls.return_value.search.return_value = None
    fake_mod = types.ModuleType("app.services.customers_service")
    fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)
    body = build_customers_query_response_dict(
        {"intent": "customers_query", "slots": {"keyword": "甲公司"}}
    )
    assert body is not None
    assert body["success"] is True
    assert "未找到" in body["response"]
    assert body["data"]["customers"] == []


def test_build_customers_query_recoverable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Constructing CustomerService raises -> except branch (lines 355-357).
    mock_cls = MagicMock(side_effect=RuntimeError("no db"))
    fake_mod = types.ModuleType("app.services.customers_service")
    fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)
    body = build_customers_query_response_dict(
        {"intent": "customers_query", "slots": {"keyword": "甲"}}
    )
    assert body is not None
    assert body["success"] is False
    assert "暂时不可用" in body["response"]
    assert body["normal_slot_dispatch"] is True


def test_build_customers_query_empty_keyword_get_all(monkeypatch: pytest.MonkeyPatch) -> None:
    # No keyword -> get_all() path with results -> formatted multi-customer msg.
    mock_cls = MagicMock()
    mock_cls.return_value.get_all.return_value = [
        {"customer_name": "甲公司", "contact_person": "张三"},
        {"customer_name": "乙公司", "contact_person": "李四"},
    ]
    fake_mod = types.ModuleType("app.services.customers_service")
    fake_mod.CustomerService = mock_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.services.customers_service", fake_mod)
    body = build_customers_query_response_dict(
        {"intent": "customers_query", "slots": {"keyword": ""}}
    )
    assert body is not None
    assert "共找到 2 位客户" in body["response"]
    mock_cls.return_value.get_all.assert_called_once()


# ---------------------------------------------------------------------------
# build_inventory_alert_response_dict — empty & except
# ---------------------------------------------------------------------------


@patch("app.application.get_material_application_service")
def test_build_inventory_alert_empty(mock_get: MagicMock) -> None:
    mock_get.return_value.get_low_stock_materials.return_value = {"data": []}
    body = build_inventory_alert_response_dict({"intent": "inventory_alert", "slots": {}})
    assert body is not None
    assert body["success"] is True
    assert "库存状态正常" in body["response"]
    assert body["data"]["low_stock_items"] == []


@patch("app.application.get_material_application_service")
def test_build_inventory_alert_recoverable_error(mock_get: MagicMock) -> None:
    mock_get.return_value.get_low_stock_materials.side_effect = RuntimeError("svc")
    body = build_inventory_alert_response_dict({"intent": "inventory_alert", "slots": {}})
    assert body is not None
    assert body["success"] is False
    assert "暂时不可用" in body["response"]
    assert body["normal_slot_dispatch"] is True


# ---------------------------------------------------------------------------
# build_label_print_response_dict — failure result & except
# ---------------------------------------------------------------------------


@patch("app.application.print_app_service.get_print_application_service")
def test_build_label_print_print_failed(mock_get: MagicMock) -> None:
    # print_single_label returns success=False -> failure message branch.
    mock_get.return_value.print_single_label.return_value = {
        "success": False,
        "message": "打印机离线",
    }
    body = build_label_print_response_dict(
        {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 3}}
    )
    assert body is not None
    assert body["success"] is False
    assert "打印失败：打印机离线" in body["response"]


@patch("app.application.print_app_service.get_print_application_service")
def test_build_label_print_recoverable_error(mock_get: MagicMock) -> None:
    mock_get.return_value.print_single_label.side_effect = RuntimeError("usb")
    body = build_label_print_response_dict(
        {"intent": "label_print", "slots": {"model_number": "A001", "quantity": 1}}
    )
    assert body is not None
    assert body["success"] is False
    assert "暂时不可用" in body["response"]
    assert body["normal_slot_dispatch"] is True
