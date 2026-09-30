"""Tests for app.services.purchase_service — purchase service coverage ramp."""

from __future__ import annotations

import contextlib
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from sqlalchemy.dialects import sqlite as sqlite_dialect

from app.db.models.purchase import PurchaseOrder
from app.services.purchase_service import PurchaseService
from app.services.purchase_service_supplier_mixin import as_date


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
            svc.create_supplier({"name": "默认值供应商"})
        call_args = mock_db.add.call_args[0][0]
        assert call_args.code.startswith("SUP")
        assert call_args.payment_terms == "月结"
        assert call_args.status == "active"
        assert call_args.rating == 3

    def test_rejects_missing_name_without_touching_db(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_supplier({"code": "S002"})
        assert result == {"success": False, "message": "供应商名称不能为空"}
        mock_db.add.assert_not_called()

    def test_duplicate_code_is_business_error(self, svc):
        from sqlalchemy.exc import IntegrityError

        mock_db = MagicMock()
        mock_db.commit.side_effect = IntegrityError("INSERT", {}, Exception("UNIQUE"))
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_supplier({"code": "S001", "name": "重复"})
        assert result["success"] is False and "S001" in result["message"]
        mock_db.rollback.assert_called_once()


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

    def test_rejects_item_without_product_before_db(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            items = [{"product_id": 1, "quantity": 1}, {"product_id": "", "quantity": 2}]
            result = svc.create_purchase_order({"supplier_id": 1, "items": items})
        assert result == {"success": False, "message": "第 2 行明细未选择产品"}
        mock_db.add.assert_not_called()

    def test_inbound_rejects_item_without_product(self, svc):
        mock_db = MagicMock()
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            items = [{"product_name": "散料", "quantity": 1}]
            result = svc.create_purchase_inbound({"items": items})
        assert result["success"] is False and "第 1 行" in result["message"]
        mock_db.add.assert_not_called()


class TestAsDate:
    """SQLite 日期列只接受 date 对象（桌面运行时），字符串必须在服务层收敛。"""

    def test_parses_iso_string(self):
        assert as_date("2026-09-27") == date(2026, 9, 27)

    def test_blank_and_none_fall_back(self):
        assert as_date("") is None
        assert as_date("   ") is None
        assert as_date(None) is None
        assert as_date("", date(2026, 1, 1)) == date(2026, 1, 1)

    def test_keeps_date_and_datetime(self):
        assert as_date(date(2026, 9, 27)) == date(2026, 9, 27)
        assert as_date(datetime(2026, 9, 27, 10, 30)) == date(2026, 9, 27)

    def test_string_dates_are_rejected_by_the_sqlite_binder(self):
        dialect = sqlite_dialect.dialect()
        order_date = PurchaseOrder.__table__.c.order_date
        binder = dialect.type_descriptor(order_date.type).bind_processor(dialect)
        with pytest.raises(TypeError):
            binder("2026-09-27")
        assert binder(as_date("2026-09-27")) is not None
        assert binder(as_date("")) is None


class TestCreatePurchaseOrderDateCoercion:
    def test_frontend_iso_dates_become_date_objects(self, svc):
        """前端提交 order_date="2026-09-27" / delivery_date="" 时必须落为 date/None。"""
        captured: dict = {}
        mock_db = MagicMock()

        def _capture(model):
            for column in model.__table__.columns:
                captured[column.name] = getattr(model, column.name, None)
            model.id = 1

        mock_db.add.side_effect = _capture
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)):
            result = svc.create_purchase_order(
                {
                    "supplier_id": 1,
                    "order_date": "2026-09-27",
                    "delivery_date": "",
                    "items": [{"product_id": 1, "quantity": 1, "unit_price": 10}],
                }
            )
        assert result["success"] is True
        assert captured["order_date"] == date(2026, 9, 27)
        assert captured["delivery_date"] is None


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
    @pytest.mark.parametrize("warehouse_id, expected", [(1, True), (2, False)])
    def test_file_sqlite_receipt_and_stock_are_atomic(
        self, svc, tmp_path, request, warehouse_id, expected
    ):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.db.base import Base
        from app.db.models import (
            InventoryLedger,
            InventoryTransaction,
            Product,
            Supplier,
            Warehouse,
        )
        from app.db.models.purchase import PurchaseInbound, PurchaseInboundItem, PurchaseOrderItem

        engine = create_engine(
            f"sqlite:///{tmp_path / 'receipt.db'}", connect_args={"timeout": 0.1}
        )
        request.addfinalizer(engine.dispose)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add_all(
                [
                    Product(id=1, name="验收产品", unit="个"),
                    Warehouse(id=1, code="W1", name="收货仓库", status="active"),
                    Supplier(id=1, code="S1", name="供应商"),
                    Warehouse(id=2, code="W2", name="停用仓库", status="disabled"),
                ]
            )
            db.add(
                PurchaseOrder(
                    id=1, order_no="PO1", supplier_id=1, status="approved", order_date=date.today()
                )
            )
            db.add(
                PurchaseOrderItem(
                    id=1,
                    order_id=1,
                    product_id=1,
                    quantity=10,
                    unit_price=12.5,
                    received_quantity=0,
                )
            )
            db.commit()

        @contextlib.contextmanager
        def database():
            with Session(engine) as db:
                yield db

        with (
            patch("app.services.purchase_service.get_db", database),
            patch("app.services.inventory_service.get_db", database),
            patch(
                "app.services.accounting_services.create_journal_entry",
                return_value={"success": True},
            ),
            patch.object(svc, "_publish_event"),
        ):
            result = svc.create_purchase_inbound(
                {
                    "order_id": 1,
                    "supplier_id": 1,
                    "warehouse_id": warehouse_id,
                    "items": [
                        {"order_item_id": 1, "product_id": 1, "quantity": 10, "unit_price": 12.5}
                    ],
                }
            )
        assert result["success"] is expected
        with Session(engine) as db:
            assert db.query(PurchaseInbound).count() == int(expected)
            assert db.query(PurchaseInboundItem).count() == int(expected)
            assert db.query(InventoryTransaction).count() == int(expected)
            ledger = db.query(InventoryLedger).first()
            assert (float(ledger.quantity) if ledger else 0) == (10 if expected else 0)
            order = db.get(PurchaseOrder, 1)
            assert order.status == ("completed" if expected else "approved")
            assert float(order.items[0].received_quantity) == (10 if expected else 0)

    def test_creates_ap_posting_with_balanced_lines(self, svc):
        """采购入库后生成『借：库存 / 贷：应付账款』复式分录，借贷平衡。"""
        mock_supplier = MagicMock()
        mock_supplier.name = "供应商A"
        mock_inbound = _make_mock_model(
            id=1,
            inbound_no="PTEST",
            supplier_id=1,
            total_amount=2000.0,
            status="completed",
        )
        mock_inbound.supplier = mock_supplier

        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        mock_db.refresh.side_effect = lambda obj: obj

        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService") as MockInvSvc,
            patch(
                "app.services.purchase_service.PurchaseInbound",
                return_value=mock_inbound,
            ),
            patch(
                "app.services.accounting_services.create_journal_entry",
                return_value={"success": True, "data": {"entry_no": "JE-001"}},
            ) as MockCreateEntry,
        ):
            MockInvSvc.return_value.inventory_in.return_value = {"success": True}
            result = svc.create_purchase_inbound(
                {
                    "inbound_no": "PTEST",
                    "supplier_id": 1,
                    "warehouse_id": 1,
                    "items": [
                        {"product_id": 1, "quantity": 10, "unit_price": 100},
                        {"product_id": 2, "quantity": 5, "unit_price": 200},
                    ],
                }
            )
        assert result["success"] is True
        MockCreateEntry.assert_called_once()
        data = MockCreateEntry.call_args.args[0]
        assert data["description"] == "采购入库: PTEST"
        assert data["reference_type"] == "purchase_inbound"
        assert data["reference_id"] == 1
        assert len(data["lines"]) >= 2
        debit_total = sum(line.get("debit", 0) for line in data["lines"])
        credit_total = sum(line.get("credit", 0) for line in data["lines"])
        assert debit_total == credit_total == 2000.0
        assert data["lines"][0] == {"account_code": "1401", "debit": 2000.0, "credit": 0}
        assert data["lines"][1] == {
            "account_code": "2201",
            "debit": 0,
            "credit": 2000.0,
            "partner_id": 1,
            "partner_name": "供应商A",
        }

    def test_skips_ap_posting_when_total_is_zero(self, svc):
        """total_amount 为 0 时不触发应付记账。"""
        mock_db = MagicMock()
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService"),
            patch(
                "app.services.accounting_services.create_journal_entry",
            ) as MockCreateEntry,
        ):
            result = svc.create_purchase_inbound({"supplier_id": 1})
        assert result["success"] is True
        MockCreateEntry.assert_not_called()

    def test_ap_posting_failure_does_not_block_inbound(self, svc):
        """应付记账失败仅告警，不阻断入库主流程。"""
        mock_product = MagicMock()
        mock_product.name = "产品A"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_product
        with (
            patch("app.services.purchase_service.get_db", _mock_get_db(mock_db)),
            patch("app.services.purchase_service.InventoryService") as MockInvSvc,
            patch(
                "app.services.accounting_services.create_journal_entry",
                return_value={"success": False, "message": "借贷不平衡"},
            ),
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
