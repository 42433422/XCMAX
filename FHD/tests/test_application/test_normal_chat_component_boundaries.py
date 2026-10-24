"""Normal chat keeps query failures and invalid write intents explicit."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application import normal_chat_dispatch as dispatch


@pytest.mark.parametrize(
    "intent,factory_path,method,message",
    [
        (
            "inventory_alert",
            "app.application.get_material_application_service",
            "get_low_stock_materials",
            None,
        ),
        (
            "finance_query",
            "app.application.finance_app_service.FinanceAppService",
            "list_transactions",
            None,
        ),
        (
            "purchase_query",
            "app.application.facades.inventory_facade.PurchaseService",
            "get_suppliers",
            "供应商",
        ),
        (
            "purchase_query",
            "app.application.facades.inventory_facade.PurchaseService",
            "get_purchase_orders",
            "采购订单",
        ),
    ],
)
def test_query_failure_is_not_reported_as_an_empty_success(intent, factory_path, method, message):
    service = MagicMock()
    getattr(service, method).return_value = {
        "success": False,
        "message": "当前用户没有读取该业务数据的权限",
        "error_code": "permission_denied",
        "data": [],
    }
    with patch(factory_path, return_value=service):
        kwargs = {} if message is None else {"message": message}
        reply = getattr(dispatch, f"build_{intent}_response_dict")(
            {"intent": intent, "slots": {}}, **kwargs
        )
    assert reply is not None
    assert reply["success"] is False
    assert "没有读取" in reply["response"]
    assert reply["data"]["intent"] == intent


@pytest.mark.parametrize(
    "quantity,price",
    [("9" * 400, "2"), ("2", "9" * 400), ("9" * 200, "9" * 200)],
    ids=["quantity-overflow", "price-overflow", "amount-overflow"],
)
def test_sales_write_intent_rejects_non_finite_amounts(quantity, price):
    request = f"把产品A卖给客户甲，{quantity}箱，单价{price}元，开票并收款"
    assert dispatch._parse_sales_write_request(request) is None


@pytest.mark.parametrize(
    "intent",
    [
        "customers_query",
        "materials_query",
        "shipment_records_query",
        "purchase_query",
        "sales_query",
    ],
)
def test_unrelated_intent_is_ignored_before_inspecting_its_slots(intent):
    assert (
        getattr(dispatch, f"build_{intent}_response_dict")(
            {"intent": "unknown", "slots": "not a business query"}
        )
        is None
    )


def test_missing_shipment_result_is_not_an_empty_success():
    service = MagicMock()
    service.get_shipment_records.return_value = None
    with patch("app.bootstrap.get_shipment_app_service", return_value=service):
        reply = dispatch.build_shipment_records_query_response_dict(
            {"intent": "shipment_records_query"}
        )
    assert reply is not None
    assert reply["success"] is False
    assert "暂时不可用" in reply["response"]


@pytest.mark.parametrize("failure_stage", ["routing", "handler", "tenant_resolution"])
def test_nested_dispatch_restores_request_and_tenant_after_failure(failure_stage):
    from app.infrastructure.request_context import (
        get_current_request,
        reset_current_request,
        set_current_request,
    )
    from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope

    outer = SimpleNamespace(state=SimpleNamespace(tenant_id=41))
    inner = SimpleNamespace(state=SimpleNamespace(tenant_id=72))

    def fail(*_args):
        assert get_current_request() is inner
        if failure_stage != "tenant_resolution":
            assert current_tenant_id() == 72
        raise RuntimeError("query aborted")

    router = MagicMock(return_value={"intent": "product_query", "slots": {}})
    handler = MagicMock(return_value={"success": True, "response": "ok"})
    resolver = MagicMock(return_value=72)
    {"routing": router, "handler": handler, "tenant_resolution": resolver}[
        failure_stage
    ].side_effect = fail
    token = set_current_request(outer)
    try:
        with (
            tenant_scope(41),
            patch.object(dispatch, "route_normal_mode_message", router),
            patch.object(dispatch, "build_product_query_response_dict", handler),
            patch.object(dispatch, "_request_tenant_id", resolver),
        ):
            with pytest.raises(RuntimeError, match="query aborted"):
                dispatch.try_normal_slot_read_payload("查询产品", request=inner)
            assert get_current_request() is outer
            assert current_tenant_id() == 41
            if failure_stage != "handler":
                handler.assert_not_called()
    finally:
        reset_current_request(token)
