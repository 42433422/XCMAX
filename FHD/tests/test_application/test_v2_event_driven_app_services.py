"""Phase 2: V2 事件驱动应用服务（customer/product/order/shipment/inventory）。"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from app.application.customer_app_service_v2 import CustomerAppServiceV2, get_customer_app_service_v2
from app.application.inventory_app_service_v2 import InventoryAppServiceV2, get_inventory_app_service_v2
from app.application.order_app_service_v2 import OrderAppServiceV2, get_order_app_service_v2
from app.application.product_app_service_v2 import ProductAppServiceV2, get_product_app_service_v2
from app.application.shipment_app_service_v2 import ShipmentAppServiceV2, get_shipment_app_service_v2


def _fake_event(*_args, **_kwargs) -> MagicMock:
    ev = MagicMock()
    ev.metadata.event_id = "evt-test"
    return ev


@pytest.fixture
def mock_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus


def _svc_with_patches(module: str, event_names: list[str], mock_bus: MagicMock):
    stack = ExitStack()
    stack.enter_context(patch(f"{module}.get_neuro_bus", return_value=mock_bus))
    for name in event_names:
        stack.enter_context(patch(f"{module}.{name}", side_effect=_fake_event))
    return stack


@pytest.fixture
def customer_svc(mock_bus: MagicMock) -> CustomerAppServiceV2:
    names = [
        "CustomerRegisteredEvent",
        "CustomerUpdatedEvent",
        "CustomerPurchaseUnitBoundEvent",
        "CustomerPreferenceUpdatedEvent",
        "CustomerDeactivatedEvent",
    ]
    with _svc_with_patches("app.application.customer_app_service_v2", names, mock_bus):
        yield CustomerAppServiceV2()


@pytest.fixture
def product_svc(mock_bus: MagicMock) -> ProductAppServiceV2:
    names = [
        "ProductCreatedEvent",
        "ProductUpdatedEvent",
        "ProductPriceChangedEvent",
        "ProductDeletedEvent",
        "ProductImportedEvent",
        "ProductCacheInvalidatedEvent",
    ]
    with _svc_with_patches("app.application.product_app_service_v2", names, mock_bus):
        yield ProductAppServiceV2()


@pytest.fixture
def order_svc(mock_bus: MagicMock) -> OrderAppServiceV2:
    names = [
        "OrderSubmittedEvent",
        "OrderPaidEvent",
        "OrderShippedEvent",
        "OrderFulfilledEvent",
        "OrderCancelledEvent",
        "OrderRefundedEvent",
    ]
    with _svc_with_patches("app.application.order_app_service_v2", names, mock_bus):
        yield OrderAppServiceV2()


@pytest.fixture
def shipment_svc(mock_bus: MagicMock) -> ShipmentAppServiceV2:
    names = [
        "ShipmentCreatedEvent",
        "ShipmentItemAddedEvent",
        "ShipmentPrintedEvent",
        "ShipmentCancelledEvent",
        "ShipmentDeletedEvent",
        "ShipmentExportedEvent",
    ]
    with _svc_with_patches("app.application.shipment_app_service_v2", names, mock_bus):
        yield ShipmentAppServiceV2()


@pytest.fixture
def inventory_svc(mock_bus: MagicMock) -> InventoryAppServiceV2:
    names = [
        "InventoryStockInEvent",
        "InventoryStockOutEvent",
        "InventoryTransferEvent",
        "InventoryStockChangedEvent",
    ]
    with _svc_with_patches("app.application.inventory_app_service_v2", names, mock_bus):
        yield InventoryAppServiceV2()


class TestCustomerAppServiceV2:
    @pytest.mark.asyncio
    async def test_register_customer(self, customer_svc: CustomerAppServiceV2, mock_bus: MagicMock):
        out = await customer_svc.register_customer({"customer_name": "甲公司", "phone": "138"})
        assert out["success"] is True
        assert out["mode"] == "event_driven"
        assert "customer_id" in out
        mock_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_customer(self, customer_svc: CustomerAppServiceV2):
        out = await customer_svc.update_customer("C1", {"phone": "139"})
        assert out["success"] is True
        assert out["customer_id"] == "C1"

    @pytest.mark.asyncio
    async def test_bind_purchase_unit(self, customer_svc: CustomerAppServiceV2):
        out = await customer_svc.bind_purchase_unit("C1", "七彩乐园")
        assert out["success"] is True
        assert out["purchase_unit"] == "七彩乐园"

    @pytest.mark.asyncio
    async def test_update_preference(self, customer_svc: CustomerAppServiceV2):
        out = await customer_svc.update_preference("C1", {"lang": "zh"})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_deactivate_customer(self, customer_svc: CustomerAppServiceV2):
        out = await customer_svc.deactivate_customer("C1", reason="inactive")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_unknown(self, customer_svc: CustomerAppServiceV2):
        out = await customer_svc.execute_command("nope", {})
        assert out["success"] is False
        assert "supported_commands" in out

    @pytest.mark.asyncio
    async def test_execute_command_register(self, customer_svc: CustomerAppServiceV2):
        out = await customer_svc.execute_command(
            "register_customer", {"data": {"customer_name": "X"}}
        )
        assert out["success"] is False or "message" in out

    @pytest.mark.asyncio
    async def test_publish_failure(self, mock_bus: MagicMock):
        mock_bus.publish.side_effect = RuntimeError("bus down")
        names = ["CustomerRegisteredEvent"]
        with _svc_with_patches("app.application.customer_app_service_v2", names, mock_bus):
            svc = CustomerAppServiceV2()
            out = await svc.register_customer({"customer_name": "X"})
        assert out["success"] is False

    def test_singleton(self):
        with patch("app.application.customer_app_service_v2.get_neuro_bus", return_value=MagicMock()):
            import app.application.customer_app_service_v2 as mod

            mod._customer_app_service_v2 = None
            a = get_customer_app_service_v2()
            b = get_customer_app_service_v2()
            assert a is b


class TestProductAppServiceV2:
    @pytest.mark.asyncio
    async def test_create_product(self, product_svc: ProductAppServiceV2, mock_bus: MagicMock):
        out = await product_svc.create_product({"product_name": "PU漆", "unit_name": "甲公司"})
        assert out["success"] is True
        assert "product_id" in out
        mock_bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_update_product(self, product_svc: ProductAppServiceV2):
        out = await product_svc.update_product("P1", {"price": 100})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_delete_product(self, product_svc: ProductAppServiceV2, mock_bus: MagicMock):
        out = await product_svc.delete_product("P1", deleted_by="admin")
        assert out["success"] is True
        assert mock_bus.publish.call_count >= 2

    @pytest.mark.asyncio
    async def test_import_products(self, product_svc: ProductAppServiceV2):
        out = await product_svc.import_products("甲公司", [{"product_name": "A"}], imported_by="u1")
        assert out["success"] is True
        assert out["count"] == 1

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, product_svc: ProductAppServiceV2):
        out = await product_svc.invalidate_cache(product_id="P1", unit_name="甲公司")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_create(self, product_svc: ProductAppServiceV2):
        out = await product_svc.execute_command("create", {"product_name": "X", "unit_name": "U"})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_unknown_publishes_raw(self, product_svc: ProductAppServiceV2):
        out = await product_svc.execute_command("custom_action", {"foo": 1})
        assert out["success"] is True
        assert out["mode"] == "event_driven"

    def test_singleton(self):
        with patch("app.application.product_app_service_v2.get_neuro_bus", return_value=MagicMock()):
            import app.application.product_app_service_v2 as mod

            mod._product_app_service_v2 = None
            assert get_product_app_service_v2() is get_product_app_service_v2()


class TestOrderAppServiceV2:
    @pytest.mark.asyncio
    async def test_submit_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.submit_order({"customer_id": "C1", "items": []})
        assert out["success"] is True
        assert "order_id" in out

    @pytest.mark.asyncio
    async def test_confirm_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.confirm_order("O1", confirmed_by="admin")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_pay_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.pay_order("O1", {"amount": 100, "method": "alipay"})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_ship_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.ship_order("O1", {"tracking_no": "TN1"})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_complete_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.complete_order("O1")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.cancel_order("O1", reason="user request")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_refund_order(self, order_svc: OrderAppServiceV2):
        out = await order_svc.refund_order("O1", {"amount": 50})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_submit(self, order_svc: OrderAppServiceV2):
        out = await order_svc.execute_command("submit_order", {"data": {"customer_id": "C1"}})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_unknown(self, order_svc: OrderAppServiceV2):
        out = await order_svc.execute_command("bad", {})
        assert out["success"] is False

    @pytest.mark.asyncio
    async def test_confirm_order_publish_failure(self, mock_bus: MagicMock):
        mock_bus.publish.side_effect = RuntimeError("fail")
        with patch("app.application.order_app_service_v2.get_neuro_bus", return_value=mock_bus):
            svc = OrderAppServiceV2()
            out = await svc.confirm_order("O1")
        assert out["success"] is False

    def test_singleton(self):
        with patch("app.application.order_app_service_v2.get_neuro_bus", return_value=MagicMock()):
            import app.application.order_app_service_v2 as mod

            mod._order_app_service_v2 = None
            assert get_order_app_service_v2() is get_order_app_service_v2()


class TestShipmentAppServiceV2:
    @pytest.mark.asyncio
    async def test_create_shipment(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.create_shipment({"unit_name": "甲公司", "items": []})
        assert out["success"] is True
        assert "shipment_id" in out

    @pytest.mark.asyncio
    async def test_add_item(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.add_item_to_shipment("S1", {"product_id": "P1", "quantity": 2})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_print_shipment(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.print_shipment("S1", {"printer": "default"})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_shipment(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.cancel_shipment("S1", reason="mistake")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_delete_shipment(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.delete_shipment("S1")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_export_shipments(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.export_shipments({"unit_name": "甲"}, "/tmp/out.xlsx")
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_create(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.execute_command("create", {"unit_name": "甲"})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_custom(self, shipment_svc: ShipmentAppServiceV2):
        out = await shipment_svc.execute_command("archive", {"id": "S1"})
        assert out["success"] is True

    def test_singleton(self):
        with patch("app.application.shipment_app_service_v2.get_neuro_bus", return_value=MagicMock()):
            import app.application.shipment_app_service_v2 as mod

            mod._shipment_app_service_v2 = None
            assert get_shipment_app_service_v2() is get_shipment_app_service_v2()


class TestInventoryAppServiceV2:
    @pytest.mark.asyncio
    async def test_stock_in(self, inventory_svc: InventoryAppServiceV2):
        out = await inventory_svc.stock_in({"product_id": "P1", "quantity": 10})
        assert out["success"] is True
        assert "batch_no" in out

    @pytest.mark.asyncio
    async def test_stock_out(self, inventory_svc: InventoryAppServiceV2):
        out = await inventory_svc.stock_out({"product_id": "P1", "quantity": 2})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_transfer(self, inventory_svc: InventoryAppServiceV2):
        out = await inventory_svc.transfer(
            {"product_id": "P1", "from_warehouse_id": "W1", "to_warehouse_id": "W2", "quantity": 1}
        )
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_adjust_stock(self, inventory_svc: InventoryAppServiceV2):
        out = await inventory_svc.adjust_stock({"product_id": "P1", "quantity_delta": -1})
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_stock_in(self, inventory_svc: InventoryAppServiceV2):
        out = await inventory_svc.execute_command(
            "stock_in", {"data": {"product_id": "P1", "quantity": 5}}
        )
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_execute_command_unknown(self, inventory_svc: InventoryAppServiceV2):
        out = await inventory_svc.execute_command("bad", {})
        assert out["success"] is False

    @pytest.mark.asyncio
    async def test_bus_failure(self, mock_bus: MagicMock):
        mock_bus.publish.side_effect = RuntimeError("bus down")
        names = ["InventoryStockInEvent"]
        with _svc_with_patches("app.application.inventory_app_service_v2", names, mock_bus):
            svc = InventoryAppServiceV2()
            out = await svc.stock_in({"product_id": "P1"})
        assert out["success"] is False

    def test_singleton(self):
        with patch("app.application.inventory_app_service_v2.get_neuro_bus", return_value=MagicMock()):
            import app.application.inventory_app_service_v2 as mod

            mod._inventory_app_service_v2 = None
            assert get_inventory_app_service_v2() is get_inventory_app_service_v2()
