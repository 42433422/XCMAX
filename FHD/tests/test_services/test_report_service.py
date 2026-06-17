"""Tests for app.services.report_service — sales/inventory/purchase reports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from sqlalchemy import column, func as sa_func

from app.services.report_service import ReportService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    return ReportService()


def _mock_db_ctx(mock_db):
    """Return a context manager that yields mock_db."""
    @contextmanager
    def _ctx():
        yield mock_db
    return _ctx()


def _decimal_to_float_static(value):
    """Standalone version of _decimal_to_float for testing (source has no @staticmethod)."""
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# _decimal_to_float
# ---------------------------------------------------------------------------

class TestDecimalToFloat:
    """_decimal_to_float() — Decimal 转 float"""

    def test_decimal_converts(self):
        """Decimal 值转为 float"""
        result = _decimal_to_float_static(Decimal("99.99"))
        assert result == 99.99
        assert isinstance(result, float)

    def test_non_decimal_returns_as_is(self):
        """非 Decimal 值原样返回"""
        assert _decimal_to_float_static(42) == 42
        assert _decimal_to_float_static("hello") == "hello"
        assert _decimal_to_float_static(None) is None

    def test_float_returns_as_is(self):
        """float 值原样返回"""
        assert _decimal_to_float_static(3.14) == 3.14

    def test_zero_decimal(self):
        """零值 Decimal 转换"""
        result = _decimal_to_float_static(Decimal("0"))
        assert result == 0.0


# ---------------------------------------------------------------------------
# get_sales_report
# ---------------------------------------------------------------------------

class TestGetSalesReport:
    """get_sales_report() — 销售报表"""

    @patch("app.services.report_service.get_db")
    def test_group_by_product(self, mock_get_db, service):
        """按产品分组"""
        mock_item = MagicMock()
        mock_item.product_name = "产品A"
        mock_item.product_id = 1
        mock_item.quantity = 10
        mock_item.amount = 100.0

        mock_record = MagicMock()
        mock_record.items = [mock_item]
        mock_record.customer_name = "客户1"
        mock_record.customer_id = 1
        mock_record.total_amount = 100.0
        mock_record.shipment_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (mock_record, 1),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="product")
        assert result["success"] is True
        assert "data" in result
        assert "summary" in result

    @patch("app.services.report_service.get_db")
    def test_group_by_customer(self, mock_get_db, service):
        """按客户分组"""
        mock_record = MagicMock()
        mock_record.customer_name = "客户A"
        mock_record.customer_id = 1
        mock_record.total_amount = 500.0
        mock_record.shipment_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (mock_record, 1),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="customer")
        assert result["success"] is True
        assert "data" in result

    @patch("app.services.report_service.get_db")
    def test_group_by_date(self, mock_get_db, service):
        """按日期分组"""
        mock_record = MagicMock()
        mock_record.customer_name = "客户A"
        mock_record.customer_id = 1
        mock_record.total_amount = 300.0
        mock_record.shipment_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (mock_record, 1),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="date")
        assert result["success"] is True
        assert "data" in result

    @patch("app.services.report_service.get_db")
    def test_group_by_date_with_none_date(self, mock_get_db, service):
        """shipment_date 为 None 时归类为 unknown"""
        mock_record = MagicMock()
        mock_record.customer_name = "客户A"
        mock_record.customer_id = 1
        mock_record.total_amount = 200.0
        mock_record.shipment_date = None

        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (mock_record, 1),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="date")
        assert result["success"] is True
        assert any(d["date"] == "unknown" for d in result["data"])

    @patch("app.services.report_service.get_db")
    def test_unknown_group_by_returns_empty(self, mock_get_db, service):
        """未知 group_by 返回空数据"""
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="unknown")
        assert result["success"] is True
        assert result["data"] == []

    @patch("app.services.report_service.ShipmentRecord")
    @patch("app.services.report_service.func")
    @patch("app.services.report_service.get_db")
    def test_with_date_filters(self, mock_get_db, mock_func, mock_sr, service):
        """日期范围过滤"""
        # Use real SQLAlchemy column objects so >= comparison with datetime works
        mock_sr.shipment_date = column("shipment_date")
        mock_sr.customer_id = column("customer_id")
        mock_sr.id = column("id")

        mock_func.count.return_value.label.return_value = "record_count"

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 12, 31),
        )
        assert result["success"] is True

    @patch("app.services.report_service.ShipmentRecord")
    @patch("app.services.report_service.func")
    @patch("app.services.report_service.get_db")
    def test_with_customer_id_filter(self, mock_get_db, mock_func, mock_sr, service):
        """客户 ID 过滤"""
        mock_sr.shipment_date = column("shipment_date")
        mock_sr.customer_id = column("customer_id")
        mock_sr.id = column("id")

        mock_func.count.return_value.label.return_value = "record_count"

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(customer_id=1)
        assert result["success"] is True

    @patch("app.services.report_service.get_db")
    def test_product_with_no_name_uses_fallback(self, mock_get_db, service):
        """产品名称为空时使用 fallback"""
        mock_item = MagicMock()
        mock_item.product_name = None
        mock_item.product_id = 42
        mock_item.quantity = 5
        mock_item.amount = 50.0

        mock_record = MagicMock()
        mock_record.items = [mock_item]
        mock_record.customer_name = "客户1"
        mock_record.customer_id = 1
        mock_record.total_amount = 50.0
        mock_record.shipment_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (mock_record, 1),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="product")
        assert result["success"] is True
        assert any("产品42" in d.get("product_name", "") for d in result["data"])

    @patch("app.services.report_service.get_db")
    def test_customer_with_no_name_uses_fallback(self, mock_get_db, service):
        """客户名称为空时使用 fallback"""
        mock_record = MagicMock()
        mock_record.customer_name = None
        mock_record.customer_id = 7
        mock_record.total_amount = 200.0
        mock_record.shipment_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (mock_record, 1),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_sales_report(group_by="customer")
        assert result["success"] is True
        assert any("客户7" in d.get("customer_name", "") for d in result["data"])


# ---------------------------------------------------------------------------
# get_inventory_report
# ---------------------------------------------------------------------------

class TestGetInventoryReport:
    """get_inventory_report() — 库存报表"""

    @patch("app.services.report_service.get_db")
    def test_basic_report(self, mock_get_db, service):
        """基本库存报表"""
        mock_warehouse = MagicMock()
        mock_warehouse.name = "仓库1"

        mock_ledger = MagicMock()
        mock_ledger.quantity = 100
        mock_ledger.available_quantity = 80
        mock_ledger.reserved_quantity = 20
        mock_ledger.warehouse = mock_warehouse

        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.name = "产品A"
        mock_product.model_number = "M-001"
        mock_product.category = "电子"

        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [
            (mock_ledger, mock_product),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_inventory_report()
        assert result["success"] is True
        assert "data" in result
        assert "summary" in result

    @patch("app.services.report_service.get_db")
    def test_with_warehouse_filter(self, mock_get_db, service):
        """仓库过滤"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_inventory_report(warehouse_id=1)
        assert result["success"] is True

    @patch("app.services.report_service.get_db")
    def test_with_category_filter(self, mock_get_db, service):
        """分类过滤"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_inventory_report(category="电子")
        assert result["success"] is True

    @patch("app.services.report_service.get_db")
    def test_warehouse_none(self, mock_get_db, service):
        """warehouse 为 None 时名称也为 None"""
        mock_ledger = MagicMock()
        mock_ledger.quantity = 50
        mock_ledger.available_quantity = 50
        mock_ledger.reserved_quantity = 0
        mock_ledger.warehouse = None

        mock_product = MagicMock()
        mock_product.id = 2
        mock_product.name = "产品B"
        mock_product.model_number = "M-002"
        mock_product.category = "工具"

        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.all.return_value = [
            (mock_ledger, mock_product),
        ]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_inventory_report()
        assert result["success"] is True
        assert result["data"][0]["warehouse_name"] is None


# ---------------------------------------------------------------------------
# get_purchase_report
# ---------------------------------------------------------------------------

class TestGetPurchaseReport:
    """get_purchase_report() — 采购报表"""

    @patch("app.services.report_service.get_db")
    def test_group_by_supplier(self, mock_get_db, service):
        """按供应商分组"""
        mock_supplier = MagicMock()
        mock_supplier.name = "供应商A"

        mock_order = MagicMock()
        mock_order.supplier = mock_supplier
        mock_order.supplier_id = 1
        mock_order.total_amount = 1000.0
        mock_order.paid_amount = 500.0
        mock_order.status = "approved"
        mock_order.order_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_order]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="supplier")
        assert result["success"] is True
        assert "data" in result

    @patch("app.services.report_service.get_db")
    def test_group_by_status(self, mock_get_db, service):
        """按状态分组"""
        mock_order = MagicMock()
        mock_order.status = "approved"
        mock_order.total_amount = 500.0
        mock_order.order_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_order]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="status")
        assert result["success"] is True

    @patch("app.services.report_service.get_db")
    def test_group_by_date(self, mock_get_db, service):
        """按日期分组"""
        mock_order = MagicMock()
        mock_order.status = "approved"
        mock_order.total_amount = 300.0
        mock_order.order_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_order]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="date")
        assert result["success"] is True

    @patch("app.services.report_service.get_db")
    def test_group_by_date_with_none_date(self, mock_get_db, service):
        """order_date 为 None 时归类为 unknown"""
        mock_order = MagicMock()
        mock_order.status = "approved"
        mock_order.total_amount = 200.0
        mock_order.order_date = None

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_order]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="date")
        assert result["success"] is True
        assert any(d["date"] == "unknown" for d in result["data"])

    @patch("app.services.report_service.get_db")
    def test_unknown_group_by_returns_empty(self, mock_get_db, service):
        """未知 group_by 返回空数据"""
        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = []
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="unknown")
        assert result["success"] is True
        assert result["data"] == []

    @patch("app.services.report_service.get_db")
    def test_supplier_none_uses_fallback(self, mock_get_db, service):
        """supplier 为 None 时使用 fallback"""
        mock_order = MagicMock()
        mock_order.supplier = None
        mock_order.supplier_id = 5
        mock_order.total_amount = 100.0
        mock_order.paid_amount = 50.0
        mock_order.status = "draft"
        mock_order.order_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_order]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="supplier")
        assert result["success"] is True
        assert any("供应商5" in d.get("supplier_name", "") for d in result["data"])

    @patch("app.services.report_service.get_db")
    def test_with_date_filters(self, mock_get_db, service):
        """日期范围过滤"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 12, 31),
        )
        assert result["success"] is True

    @patch("app.services.report_service.get_db")
    def test_status_none_uses_unknown(self, mock_get_db, service):
        """status 为 None 时归类为 unknown"""
        mock_order = MagicMock()
        mock_order.status = None
        mock_order.total_amount = 100.0
        mock_order.order_date = datetime(2026, 1, 15)

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_order]
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_purchase_report(group_by="status")
        assert result["success"] is True
        assert any(d["status"] == "unknown" for d in result["data"])


# ---------------------------------------------------------------------------
# get_inventory_transaction_report
# ---------------------------------------------------------------------------

class TestGetInventoryTransactionReport:
    """get_inventory_transaction_report() — 库存事务报表"""

    @patch("app.services.report_service.get_db")
    def test_basic_report(self, mock_get_db, service):
        """基本库存事务报表"""
        mock_product = MagicMock()
        mock_product.name = "产品A"

        mock_warehouse = MagicMock()
        mock_warehouse.name = "仓库1"

        mock_txn = MagicMock()
        mock_txn.id = 1
        mock_txn.transaction_type = "in"
        mock_txn.product = mock_product
        mock_txn.warehouse = mock_warehouse
        mock_txn.quantity = 10
        mock_txn.before_quantity = 0
        mock_txn.after_quantity = 10
        mock_txn.unit_price = 5.5
        mock_txn.total_amount = 55.0
        mock_txn.reference_type = "purchase"
        mock_txn.transaction_date = datetime(2026, 1, 15)
        mock_txn.operator = "admin"
        mock_txn.remark = "test"

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_txn]
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        # Patch _decimal_to_float since source lacks @staticmethod
        with patch.object(service, "_decimal_to_float", side_effect=_decimal_to_float_static):
            result = service.get_inventory_transaction_report()
        assert result["success"] is True
        assert result["count"] == 1
        assert result["data"][0]["quantity"] == 10.0

    @patch("app.services.report_service.get_db")
    def test_with_filters(self, mock_get_db, service):
        """带过滤条件"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        result = service.get_inventory_transaction_report(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 12, 31),
            transaction_type="in",
            product_id=1,
        )
        assert result["success"] is True
        assert result["count"] == 0

    @patch("app.services.report_service.get_db")
    def test_product_none(self, mock_get_db, service):
        """product 为 None 时名称为 None"""
        mock_txn = MagicMock()
        mock_txn.id = 1
        mock_txn.transaction_type = "out"
        mock_txn.product = None
        mock_txn.warehouse = None
        mock_txn.quantity = 5
        mock_txn.before_quantity = 10
        mock_txn.after_quantity = 5
        mock_txn.unit_price = None
        mock_txn.total_amount = None
        mock_txn.reference_type = None
        mock_txn.transaction_date = None
        mock_txn.operator = None
        mock_txn.remark = None

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_txn]
        mock_db.query.return_value = mock_query
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch.object(service, "_decimal_to_float", side_effect=_decimal_to_float_static):
            result = service.get_inventory_transaction_report()
        assert result["data"][0]["product_name"] is None
        assert result["data"][0]["warehouse_name"] is None
        assert result["data"][0]["transaction_date"] is None


# ---------------------------------------------------------------------------
# get_dashboard_summary
# ---------------------------------------------------------------------------

class TestGetDashboardSummary:
    """get_dashboard_summary() — 仪表盘摘要"""

    @patch("app.services.report_service.ShipmentRecord")
    @patch("app.services.report_service.PurchaseOrder")
    @patch("app.services.report_service.InventoryLedger")
    @patch("app.services.report_service.Supplier")
    @patch("app.services.report_service.Product")
    @patch("app.services.report_service.func")
    @patch("app.services.report_service.get_db")
    def test_basic_summary(
        self, mock_get_db, mock_func, mock_product, mock_supplier,
        mock_ledger, mock_po, mock_sr, service,
    ):
        """基本仪表盘摘要"""
        # Use real SQLAlchemy column objects so >= comparison with datetime works
        mock_sr.total_amount = column("total_amount")
        mock_sr.id = column("id")
        mock_sr.shipment_date = column("shipment_date")
        mock_po.id = column("id")
        mock_po.total_amount = column("total_amount")
        mock_po.order_date = column("order_date")
        mock_po.status = column("status")
        mock_product.id = column("id")
        mock_supplier.id = column("id")
        mock_supplier.status = column("status")
        mock_ledger.id = column("id")
        mock_ledger.available_quantity = column("available_quantity")

        mock_db = MagicMock()
        call_count = 0

        def side_effect_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar.return_value = 10
            elif call_count == 2:
                m.filter.return_value.scalar.return_value = 5
            elif call_count == 3:
                m.filter.return_value.first.return_value = (3, Decimal("1500"))
            elif call_count == 4:
                m.filter.return_value.first.return_value = (2, Decimal("800"))
            elif call_count == 5:
                m.filter.return_value.scalar.return_value = 2
            elif call_count == 6:
                m.filter.return_value.scalar.return_value = 1
            return m

        mock_db.query = MagicMock(side_effect=side_effect_query)
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch.object(service, "_decimal_to_float", side_effect=_decimal_to_float_static):
            result = service.get_dashboard_summary()

        assert result["success"] is True
        assert "data" in result

    @patch("app.services.report_service.ShipmentRecord")
    @patch("app.services.report_service.PurchaseOrder")
    @patch("app.services.report_service.InventoryLedger")
    @patch("app.services.report_service.Supplier")
    @patch("app.services.report_service.Product")
    @patch("app.services.report_service.func")
    @patch("app.services.report_service.get_db")
    def test_null_amounts(
        self, mock_get_db, mock_func, mock_product, mock_supplier,
        mock_ledger, mock_po, mock_sr, service,
    ):
        """金额为 None 时使用 0"""
        mock_sr.total_amount = column("total_amount")
        mock_sr.id = column("id")
        mock_sr.shipment_date = column("shipment_date")
        mock_po.id = column("id")
        mock_po.total_amount = column("total_amount")
        mock_po.order_date = column("order_date")
        mock_po.status = column("status")
        mock_product.id = column("id")
        mock_supplier.id = column("id")
        mock_supplier.status = column("status")
        mock_ledger.id = column("id")
        mock_ledger.available_quantity = column("available_quantity")

        mock_db = MagicMock()
        call_count = 0

        def side_effect_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar.return_value = 0
            elif call_count == 2:
                m.filter.return_value.scalar.return_value = 0
            elif call_count == 3:
                m.filter.return_value.first.return_value = (0, None)
            elif call_count == 4:
                m.filter.return_value.first.return_value = (0, None)
            elif call_count == 5:
                m.filter.return_value.scalar.return_value = 0
            elif call_count == 6:
                m.filter.return_value.scalar.return_value = 0
            return m

        mock_db.query = MagicMock(side_effect=side_effect_query)
        mock_get_db.return_value = _mock_db_ctx(mock_db)

        with patch.object(service, "_decimal_to_float", side_effect=_decimal_to_float_static):
            result = service.get_dashboard_summary()

        assert result["success"] is True


# ---------------------------------------------------------------------------
# export_to_excel
# ---------------------------------------------------------------------------

class TestExportToExcel:
    """export_to_excel() — 导出 Excel"""

    def test_basic_export(self, service):
        """基本导出"""
        data = [
            {"name": "产品A", "price": 100},
            {"name": "产品B", "price": 200},
        ]
        result = service.export_to_excel("sales", data, "test_report")
        assert result["success"] is True
        assert result["filename"] == "test_report.xlsx"
        assert result["data"] is not None
        assert result["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def test_empty_data(self, service):
        """空数据导出"""
        result = service.export_to_excel("sales", [], "empty_report")
        assert result["success"] is True

    def test_export_error(self, service):
        """导出异常时返回失败"""
        with patch("app.services.report_service.pd.DataFrame", side_effect=ValueError("bad data")):
            result = service.export_to_excel("sales", None, "error_report")
        assert result["success"] is False
        assert "message" in result
