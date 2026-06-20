"""Tests for app.services.purchase_service — purchase service coverage ramp."""

from __future__ import annotations

import contextlib
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.services.purchase_service import PurchaseService


def _mock_get_db(mock_db):
    """Create a contextmanager mock for get_db generator."""

    @contextlib.contextmanager
    def _get_db():
        yield mock_db

    return _get_db


def _make_mock_model(**fields):
    """Create a mock model object with __table__ for _model_to_dict."""
    model = MagicMock()
    cols = []
    for name, value in fields.items():
        col = MagicMock()
        col.name = name
        cols.append(col)
        setattr(model, name, value)
    model.__table__ = MagicMock()
    model.__table__.columns = cols
    return model


@pytest.fixture
def svc():
    return PurchaseService()


# ---------------------------------------------------------------------------
# _decimal_to_float / _model_to_dict
# ---------------------------------------------------------------------------


class TestDecimalToFloat:
    def test_converts_decimal(self):
        assert PurchaseService._decimal_to_float(Decimal("3.14")) == 3.14

    def test_passes_through_non_decimal(self):
        assert PurchaseService._decimal_to_float(42) == 42
        assert PurchaseService._decimal_to_float("hello") == "hello"
        assert PurchaseService._decimal_to_float(None) is None


class TestModelToDict:
    def test_returns_empty_for_none(self):
        assert PurchaseService._model_to_dict(None) == {}

    def test_converts_model_columns(self):
        model = _make_mock_model(id=1, amount=Decimal("9.99"))
        result = PurchaseService._model_to_dict(model)
        assert result["id"] == 1
        assert result["amount"] == 9.99


# ---------------------------------------------------------------------------
# Supplier CRUD
# ---------------------------------------------------------------------------


class TestGetSuppliers:
    def test_returns_all_suppliers(self, svc):
        mock_supplier = _make_mock_model(id=1, name="测试供应商")
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.all.return_value = [mock_supplier]
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_suppliers()
        assert result["success"] is True
        assert result["count"] == 1

    def test_filters_by_status(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_suppliers(status="active")
        assert result["success"] is True

    def test_filters_by_keyword(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_suppliers(keyword="测试")
        assert result["success"] is True


class TestGetSupplier:
    def test_returns_supplier_when_found(self, svc):
        mock_supplier = _make_mock_model(id=1, name="测试供应商")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_supplier
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_supplier(1)
        assert result["success"] is True

    def test_returns_failure_when_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_supplier(999)
        assert result["success"] is False
        assert "不存在" in result["message"]


class TestCreateSupplier:
    def test_creates_supplier_successfully(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_supplier({"code": "S001", "name": "测试供应商"})
        assert result["success"] is True

    def test_returns_failure_on_db_error(self, svc):
        mock_db = MagicMock()
        mock_db.add.side_effect = OSError("db error")
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_supplier({"code": "S001", "name": "测试供应商"})
        assert result["success"] is False

    def test_uses_default_values(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            svc.create_supplier({})
        call_args = mock_db.add.call_args[0][0]
        assert call_args.payment_terms == "月结"
        assert call_args.status == "active"
        assert call_args.rating == 3


class TestUpdateSupplier:
    def test_updates_existing_supplier(self, svc):
        mock_supplier = _make_mock_model(id=1, name="旧名称")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_supplier
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_supplier(1, {"name": "新名称"})
        assert result["success"] is True

    def test_returns_failure_when_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_supplier(999, {"name": "新名称"})
        assert result["success"] is False

    def test_returns_failure_on_db_error(self, svc):
        mock_supplier = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_supplier
        mock_db.commit.side_effect = OSError("db error")
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_supplier(1, {"name": "新名称"})
        assert result["success"] is False


class TestDeleteSupplier:
    def test_soft_deletes_supplier(self, svc):
        mock_supplier = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_supplier
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.delete_supplier(1)
        assert result["success"] is True
        assert mock_supplier.status == "deleted"

    def test_returns_failure_when_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.delete_supplier(999)
        assert result["success"] is False

    def test_returns_failure_on_db_error(self, svc):
        mock_supplier = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_supplier
        mock_db.commit.side_effect = OSError("db error")
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.delete_supplier(1)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Purchase Orders
# ---------------------------------------------------------------------------


class TestGetPurchaseOrders:
    def test_returns_orders_with_pagination(self, svc):
        mock_order = _make_mock_model(id=1, status="draft")
        mock_order.supplier = MagicMock()
        mock_order.supplier.name = "供应商A"
        mock_order.items = []
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_order
        ]
        mock_db.query.return_value.join.return_value.count.return_value = 1
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_orders(page=1, per_page=10)
        assert result["success"] is True
        assert result["total"] == 1
        assert result["page"] == 1

    def test_filters_by_supplier_id(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.join.return_value.filter.return_value.count.return_value = 0
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_orders(supplier_id=1)
        assert result["success"] is True

    def test_filters_by_status(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.join.return_value.filter.return_value.count.return_value = 0
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_orders(status="draft")
        assert result["success"] is True

    def test_filters_by_date_range(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.join.return_value.filter.return_value.filter.return_value.filter.return_value.count.return_value = 0
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_orders(
                start_date=datetime(2026, 1, 1),
                end_date=datetime(2026, 12, 31),
            )
        assert result["success"] is True


class TestGetPurchaseOrder:
    def test_returns_order_with_details(self, svc):
        mock_item = _make_mock_model(id=1, product_name="产品A")
        mock_item.product = MagicMock()
        mock_item.product.name = "产品A"
        mock_order = _make_mock_model(id=1, status="draft")
        mock_order.supplier = MagicMock()
        mock_order.supplier.name = "供应商A"
        mock_order.warehouse = MagicMock()
        mock_order.warehouse.name = "仓库1"
        mock_order.items = [mock_item]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_order(1)
        assert result["success"] is True
        assert "items" in result["data"]

    def test_returns_failure_when_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_order(999)
        assert result["success"] is False


class TestCreatePurchaseOrder:
    def test_creates_order_with_items(self, svc):
        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_purchase_order(
                {
                    "supplier_id": 1,
                    "warehouse_id": 1,
                    "items": [
                        {"product_id": 1, "quantity": 10, "unit_price": 100},
                        {"product_id": 2, "quantity": 5, "unit_price": 200},
                    ],
                }
            )
        assert result["success"] is True
        assert "创建成功" in result["message"]

    def test_creates_order_without_items(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_purchase_order({"supplier_id": 1})
        assert result["success"] is True

    def test_generates_order_no_when_not_provided(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_purchase_order({})
        assert result["success"] is True

    def test_returns_failure_on_db_error(self, svc):
        mock_db = MagicMock()
        mock_db.add.side_effect = OSError("db error")
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_purchase_order({"supplier_id": 1})
        assert result["success"] is False


class TestUpdatePurchaseOrder:
    def test_updates_draft_order(self, svc):
        mock_order = _make_mock_model(id=1, status="draft")
        mock_order.items = []
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_purchase_order(1, {"remark": "updated"})
        assert result["success"] is True

    def test_rejects_update_for_non_draft_order(self, svc):
        mock_order = MagicMock()
        mock_order.status = "approved"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_purchase_order(1, {"remark": "updated"})
        assert result["success"] is False
        assert "草稿" in result["message"]

    def test_allows_update_for_rejected_order(self, svc):
        mock_order = _make_mock_model(id=1, status="rejected")
        mock_order.items = []
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_purchase_order(1, {"remark": "updated"})
        assert result["success"] is True

    def test_returns_failure_when_order_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_purchase_order(999, {"remark": "updated"})
        assert result["success"] is False

    def test_replaces_items_when_provided(self, svc):
        mock_order = _make_mock_model(id=1, status="draft")
        mock_order.items = []
        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        # First query returns order, second returns product
        mock_db.query.side_effect = [
            MagicMock(
                filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_order)))
            ),
            MagicMock(filter=MagicMock(return_value=MagicMock(delete=MagicMock(return_value=0)))),
            MagicMock(
                filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_product)))
            ),
        ]
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.update_purchase_order(
                1,
                {
                    "items": [{"product_id": 1, "quantity": 5, "unit_price": 50}],
                },
            )
        assert result["success"] is True


class TestApprovePurchaseOrder:
    def test_approves_draft_order(self, svc):
        mock_item = MagicMock()
        mock_order = MagicMock()
        mock_order.status = "draft"
        mock_order.items = [mock_item]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.approve_purchase_order(1, "admin")
        assert result["success"] is True
        assert mock_order.status == "approved"
        assert mock_item.status == "approved"

    def test_rejects_non_draft_order(self, svc):
        mock_order = MagicMock()
        mock_order.status = "approved"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.approve_purchase_order(1, "admin")
        assert result["success"] is False
        assert "草稿" in result["message"]

    def test_returns_failure_when_order_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.approve_purchase_order(999, "admin")
        assert result["success"] is False


class TestCancelPurchaseOrder:
    def test_cancels_draft_order(self, svc):
        mock_item = MagicMock()
        mock_order = MagicMock()
        mock_order.status = "draft"
        mock_order.items = [mock_item]
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.cancel_purchase_order(1)
        assert result["success"] is True
        assert mock_order.status == "cancelled"
        assert mock_item.status == "cancelled"

    def test_rejects_cancelling_completed_order(self, svc):
        mock_order = MagicMock()
        mock_order.status = "completed"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.cancel_purchase_order(1)
        assert result["success"] is False
        assert "无法取消" in result["message"]

    def test_rejects_cancelling_already_cancelled_order(self, svc):
        mock_order = MagicMock()
        mock_order.status = "cancelled"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.cancel_purchase_order(1)
        assert result["success"] is False

    def test_returns_failure_when_order_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.cancel_purchase_order(999)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Purchase Inbound
# ---------------------------------------------------------------------------


class TestCreatePurchaseInbound:
    def test_creates_inbound_with_items(self, svc):
        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService") as MockInvSvc,
        ):
            MockInvSvc.return_value.inventory_in.return_value = {"success": True}
            result = svc.create_purchase_inbound(
                {
                    "supplier_id": 1,
                    "warehouse_id": 1,
                    "items": [{"product_id": 1, "quantity": 10, "unit_price": 100}],
                }
            )
        assert result["success"] is True
        assert "入库成功" in result["message"]

    def test_creates_inbound_without_items(self, svc):
        mock_db = MagicMock()
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService"),
        ):
            result = svc.create_purchase_inbound({"supplier_id": 1, "warehouse_id": 1})
        assert result["success"] is True

    def test_returns_failure_on_db_error(self, svc):
        mock_db = MagicMock()
        mock_db.add.side_effect = OSError("db error")
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService"),
        ):
            result = svc.create_purchase_inbound({"supplier_id": 1})
        assert result["success"] is False

    def test_logs_warning_when_inventory_in_fails(self, svc):
        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService") as MockInvSvc,
        ):
            MockInvSvc.return_value.inventory_in.return_value = {
                "success": False,
                "message": "库存不足",
            }
            result = svc.create_purchase_inbound(
                {
                    "supplier_id": 1,
                    "warehouse_id": 1,
                    "items": [{"product_id": 1, "quantity": 10, "unit_price": 100}],
                }
            )
        assert result["success"] is True

    def test_updates_order_received_quantity(self, svc):
        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService") as MockInvSvc,
        ):
            MockInvSvc.return_value.inventory_in.return_value = {"success": True}
            result = svc.create_purchase_inbound(
                {
                    "supplier_id": 1,
                    "warehouse_id": 1,
                    "order_id": 1,
                    "items": [{"product_id": 1, "quantity": 10, "unit_price": 100}],
                }
            )
        assert result["success"] is True


class TestUpdateOrderReceivedQuantity:
    def test_marks_item_completed_when_fully_received(self, svc):
        mock_db = MagicMock()
        mock_order = MagicMock()
        mock_item = MagicMock()
        mock_item.id = 1
        mock_item.quantity = 10
        mock_item.received_quantity = 0
        mock_order.items = [mock_item]
        mock_inbound_item = MagicMock()
        mock_inbound_item.quantity = 10
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_inbound_item]
        svc._update_order_received_quantity(mock_db, 1)
        assert mock_item.status == "completed"
        assert mock_order.status == "completed"

    def test_marks_item_partial_when_partially_received(self, svc):
        mock_db = MagicMock()
        mock_order = MagicMock()
        mock_item = MagicMock()
        mock_item.id = 1
        mock_item.quantity = 10
        mock_item.received_quantity = 0
        mock_order.items = [mock_item]
        mock_inbound_item = MagicMock()
        mock_inbound_item.quantity = 5
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_inbound_item]
        svc._update_order_received_quantity(mock_db, 1)
        assert mock_item.status == "partial"
        assert mock_order.status == "partial"

    def test_skips_when_order_not_found(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        svc._update_order_received_quantity(mock_db, 999)


class TestGetPurchaseInbounds:
    def test_returns_inbounds_with_pagination(self, svc):
        mock_inbound = _make_mock_model(id=1, status="completed")
        mock_inbound.supplier = MagicMock()
        mock_inbound.supplier.name = "供应商A"
        mock_inbound.warehouse = MagicMock()
        mock_inbound.warehouse.name = "仓库1"
        mock_inbound.items = []
        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_inbound
        ]
        mock_db.query.return_value.count.return_value = 1
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_inbounds(page=1, per_page=10)
        assert result["success"] is True
        assert result["total"] == 1

    def test_filters_by_supplier_and_order(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.filter.return_value.count.return_value = 0
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_inbounds(supplier_id=1, order_id=2)
        assert result["success"] is True

    def test_filters_by_date_range(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.filter.return_value.filter.return_value.count.return_value = 0
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_inbounds(
                start_date=datetime(2026, 1, 1),
                end_date=datetime(2026, 12, 31),
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestGetSupplierSummary:
    def test_returns_summary(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            ("active", 5),
            ("deleted", 1),
        ]
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_supplier_summary()
        assert result["success"] is True
        assert result["data"]["active"] == 5

    def test_handles_null_status(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (None, 2),
        ]
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_supplier_summary()
        assert result["success"] is True
        assert result["data"]["unknown"] == 2


class TestGetPurchaseSummary:
    def test_returns_summary(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            ("draft", 3, Decimal("1000.00")),
            ("approved", 2, Decimal("5000.00")),
        ]
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_summary()
        assert result["success"] is True
        assert result["data"]["draft"]["count"] == 3
        assert result["data"]["draft"]["amount"] == 1000.0

    def test_filters_by_date_range(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.group_by.return_value.all.return_value = []
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_summary(
                start_date=datetime(2026, 1, 1),
                end_date=datetime(2026, 12, 31),
            )
        assert result["success"] is True

    def test_handles_none_amount(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            ("draft", 1, None),
        ]
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.get_purchase_summary()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Order/Inbound number generation
# ---------------------------------------------------------------------------


class TestGenerateOrderNo:
    def test_generates_po_prefix(self, svc):
        result = svc._generate_order_no()
        assert result.startswith("PO")
        assert len(result) > 2


class TestGenerateInboundNo:
    def test_generates_pi_prefix(self, svc):
        result = svc._generate_inbound_no()
        assert result.startswith("PI")
