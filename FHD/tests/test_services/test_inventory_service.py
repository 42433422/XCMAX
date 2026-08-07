"""Tests for app.services.inventory_service — coverage ramp."""

from __future__ import annotations

import contextlib
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
from app.services.inventory_service import InventoryService


def _mock_get_db(mock_db):
    """Create a contextmanager mock for get_db generator."""

    @contextlib.contextmanager
    def _get_db():
        yield mock_db

    return _get_db


@pytest.fixture(scope="function")
def test_engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture(scope="function")
def test_session(test_engine):
    Base.metadata.create_all(test_engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# _decimal_to_float
# ---------------------------------------------------------------------------
class TestDecimalToFloat:
    def test_decimal_converted(self):
        assert InventoryService._decimal_to_float(Decimal("10.5")) == 10.5

    def test_int_unchanged(self):
        assert InventoryService._decimal_to_float(42) == 42

    def test_float_unchanged(self):
        assert InventoryService._decimal_to_float(3.14) == 3.14

    def test_string_unchanged(self):
        assert InventoryService._decimal_to_float("hello") == "hello"

    def test_none_unchanged(self):
        assert InventoryService._decimal_to_float(None) is None


# ---------------------------------------------------------------------------
# _model_to_dict
# ---------------------------------------------------------------------------
class TestModelToDict:
    def test_none_returns_empty(self):
        assert InventoryService._model_to_dict(None) == {}

    def test_model_converted(self):
        mock_model = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "id"
        mock_model.__table__ = MagicMock()
        mock_model.__table__.columns = [mock_col]
        mock_model.id = 42
        result = InventoryService._model_to_dict(mock_model)
        assert result["id"] == 42

    def test_decimal_in_model(self):
        mock_model = MagicMock()
        mock_col = MagicMock()
        mock_col.name = "price"
        mock_model.__table__ = MagicMock()
        mock_model.__table__.columns = [mock_col]
        mock_model.price = Decimal("99.99")
        result = InventoryService._model_to_dict(mock_model)
        assert result["price"] == 99.99


# ---------------------------------------------------------------------------
# get_warehouses
# ---------------------------------------------------------------------------
class TestGetWarehouses:
    @patch("app.services.inventory_service.get_db")
    def test_list_warehouses(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_warehouse = MagicMock()
        mock_warehouse.__table__ = MagicMock()
        mock_warehouse.__table__.columns = []
        mock_db.query.return_value.order_by.return_value.all.return_value = [mock_warehouse]
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_warehouses()
        assert result["success"] is True
        assert result["count"] == 1

    @patch("app.services.inventory_service.get_db")
    def test_list_warehouses_with_status_filter(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_warehouses(status="active")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# get_warehouse
# ---------------------------------------------------------------------------
class TestGetWarehouse:
    @patch("app.services.inventory_service.get_db")
    def test_warehouse_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_warehouse = MagicMock()
        mock_warehouse.__table__ = MagicMock()
        mock_warehouse.__table__.columns = []
        mock_db.query.return_value.filter.return_value.first.return_value = mock_warehouse
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_warehouse(1)
        assert result["success"] is True

    @patch("app.services.inventory_service.get_db")
    def test_warehouse_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_warehouse(999)
        assert result["success"] is False
        assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# create_warehouse
# ---------------------------------------------------------------------------
class TestCreateWarehouse:
    @patch("app.services.inventory_service.get_db")
    def test_create_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_warehouse = MagicMock()
        mock_warehouse.__table__ = MagicMock()
        mock_warehouse.__table__.columns = []
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None
        # Make the Warehouse constructor return our mock
        with patch("app.services.inventory_service.Warehouse", return_value=mock_warehouse):
            svc = InventoryService()
            result = svc.create_warehouse({"code": "WH01", "name": "Main"})
        assert result["success"] is True

    @patch("app.services.inventory_service.get_db")
    def test_create_error(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.add.side_effect = RuntimeError("db error")
        mock_db.rollback.return_value = None
        mock_get_db.return_value = mock_db
        mock_warehouse = MagicMock()
        mock_warehouse.__table__ = MagicMock()
        mock_warehouse.__table__.columns = []
        with patch("app.services.inventory_service.Warehouse", return_value=mock_warehouse):
            svc = InventoryService()
            result = svc.create_warehouse({"code": "WH01"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# update_warehouse
# ---------------------------------------------------------------------------
class TestUpdateWarehouse:
    @patch("app.services.inventory_service.get_db")
    def test_update_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_warehouse = MagicMock()
        mock_warehouse.__table__ = MagicMock()
        mock_warehouse.__table__.columns = []
        mock_db.query.return_value.filter.return_value.first.return_value = mock_warehouse
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.update_warehouse(1, {"name": "Updated"})
        assert result["success"] is True

    @patch("app.services.inventory_service.get_db")
    def test_update_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.update_warehouse(999, {"name": "Updated"})
        assert result["success"] is False

    @patch("app.services.inventory_service.get_db")
    def test_update_error(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_warehouse = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_warehouse
        mock_db.commit.side_effect = RuntimeError("db error")
        mock_db.rollback.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.update_warehouse(1, {"name": "Updated"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# delete_warehouse
# ---------------------------------------------------------------------------
class TestDeleteWarehouse:
    @patch("app.services.inventory_service.get_db")
    def test_delete_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_warehouse = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_warehouse
        mock_db.commit.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.delete_warehouse(1)
        assert result["success"] is True

    @patch("app.services.inventory_service.get_db")
    def test_delete_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.delete_warehouse(999)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# get_storage_locations
# ---------------------------------------------------------------------------
class TestGetStorageLocations:
    @patch("app.services.inventory_service.get_db")
    def test_list_locations(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_loc = MagicMock()
        mock_loc.__table__ = MagicMock()
        mock_loc.__table__.columns = []
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_loc
        ]
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_storage_locations(warehouse_id=1)
        assert result["success"] is True

    @patch("app.services.inventory_service.get_db")
    def test_list_locations_with_status(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_storage_locations(warehouse_id=1, status="active")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# create_storage_location
# ---------------------------------------------------------------------------
class TestCreateStorageLocation:
    @patch("app.services.inventory_service.get_db")
    def test_create_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_loc = MagicMock()
        mock_loc.__table__ = MagicMock()
        mock_loc.__table__.columns = []
        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None
        with patch("app.services.inventory_service.StorageLocation", return_value=mock_loc):
            svc = InventoryService()
            result = svc.create_storage_location(
                {"warehouse_id": 1, "code": "LOC01", "name": "A-1"}
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# update_storage_location
# ---------------------------------------------------------------------------
class TestUpdateStorageLocation:
    @patch("app.services.inventory_service.get_db")
    def test_update_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_loc = MagicMock()
        mock_loc.__table__ = MagicMock()
        mock_loc.__table__.columns = []
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loc
        mock_db.commit.return_value = None
        mock_db.refresh.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.update_storage_location(1, {"code": "LOC02"})
        assert result["success"] is True

    @patch("app.services.inventory_service.get_db")
    def test_update_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.update_storage_location(999, {"code": "LOC02"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# get_inventory
# ---------------------------------------------------------------------------
class TestGetInventory:
    @patch("app.services.inventory_service.get_db")
    def test_list_inventory(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_item = MagicMock()
        mock_item.__table__ = MagicMock()
        mock_item.__table__.columns = []
        mock_item.product = MagicMock(name="Product A", model_number="ABC-123")
        mock_item.warehouse = MagicMock(name="Main WH")
        mock_item.location = MagicMock(name="A-1")
        mock_db.query.return_value.join.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_item
        ]
        mock_db.query.return_value.join.return_value.count.return_value = 1
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_inventory()
        assert result["success"] is True
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# get_inventory_summary
# ---------------------------------------------------------------------------
class TestGetInventorySummary:
    @patch("app.services.inventory_service.get_db")
    def test_summary(self, mock_get_db):
        mock_item = MagicMock()
        mock_item.product_id = 1
        mock_item.product_name = "Product A"
        mock_item.model_number = "ABC-123"
        mock_item.total_quantity = Decimal("100")
        mock_item.total_available = Decimal("80")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.join.return_value.group_by.return_value.all.return_value = [
            mock_item
        ]
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_inventory_summary()
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["total_quantity"] == 100.0


# ---------------------------------------------------------------------------
# inventory_in
# ---------------------------------------------------------------------------
class TestInventoryIn:
    @patch("app.services.inventory_service.get_db")
    def test_product_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.inventory_in(product_id=999, warehouse_id=1, quantity=10)
        assert result["success"] is False
        assert "产品不存在" in result["message"]


# ---------------------------------------------------------------------------
# inventory_out
# ---------------------------------------------------------------------------
class TestInventoryOut:
    @patch("app.services.inventory_service.get_db")
    def test_insufficient_stock(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.inventory_out(product_id=1, warehouse_id=1, quantity=100)
        assert result["success"] is False
        assert "库存不足" in result["message"]


# ---------------------------------------------------------------------------
# inventory_transfer
# ---------------------------------------------------------------------------
class TestInventoryTransfer:
    @patch("app.services.inventory_service.get_db")
    def test_source_insufficient(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.inventory_transfer(
            product_id=1, from_warehouse_id=1, to_warehouse_id=2, quantity=100
        )
        assert result["success"] is False
        assert "库存不足" in result["message"]


# ---------------------------------------------------------------------------
# get_inventory_transactions
# ---------------------------------------------------------------------------
class TestGetInventoryTransactions:
    @patch("app.services.inventory_service.get_db")
    def test_list_transactions(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_item = MagicMock()
        mock_item.__table__ = MagicMock()
        mock_item.__table__.columns = []
        mock_item.product = MagicMock(name="Product A")
        mock_item.warehouse = MagicMock(name="Main WH")
        mock_item.location = MagicMock(name="A-1")
        mock_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_item
        ]
        mock_db.query.return_value.count.return_value = 1
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_inventory_transactions()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# get_inventory_alert
# ---------------------------------------------------------------------------
class TestGetInventoryAlert:
    @patch("app.services.inventory_service.get_db")
    def test_alert_list(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_item = MagicMock()
        mock_item.__table__ = MagicMock()
        mock_item.__table__.columns = []
        mock_item.product = MagicMock(name="Product A", model_number="ABC-123")
        mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = [
            mock_item
        ]
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.get_inventory_alert()
        assert result["success"] is True
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# inventory_count — Mock 风格（未确认）
# ---------------------------------------------------------------------------
class TestInventoryCountUnconfirmed:
    @patch("app.services.inventory_service.get_db")
    def test_unconfirmed_returns_diff_without_changing_stock(self, mock_get_db):
        """盘点未确认：库存不变，返回差异供对话层反问确认。"""
        mock_ledger = MagicMock()
        mock_ledger.quantity = Decimal("100")
        mock_ledger.available_quantity = Decimal("90")
        mock_ledger.id = 1

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_ledger
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.inventory_count(
            product_id=1, warehouse_id=1, actual_quantity=110, confirmed=False
        )

        assert result["success"] is True
        assert result["confirmed"] is False
        assert result["data"]["book_quantity"] == 100.0
        assert result["data"]["actual_quantity"] == 110.0
        assert result["data"]["diff"] == 10.0
        # 未确认不应改动库存
        mock_db.commit.assert_not_called()
        mock_db.add.assert_not_called()

    @patch("app.services.inventory_service.get_db")
    def test_ledger_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.inventory_count(product_id=1, warehouse_id=1, actual_quantity=10)
        assert result["success"] is False
        assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# inventory_count — 确认（真实 sqlite :memory:）
# ---------------------------------------------------------------------------
class TestInventoryCountConfirmed:
    def _seed(self, db):
        wh = Warehouse(code="WH01", name="主仓", status="active")
        prod = Product(name="商品A", model_number="P-001", unit="个")
        db.add_all([wh, prod])
        db.commit()
        db.refresh(wh)
        db.refresh(prod)
        ledger = InventoryLedger(
            product_id=prod.id,
            warehouse_id=wh.id,
            batch_no=None,
            quantity=Decimal("100"),
            available_quantity=Decimal("90"),
            reserved_quantity=Decimal("10"),
            unit="个",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(ledger)
        db.commit()
        db.refresh(ledger)
        return wh, prod, ledger

    def test_confirmed_adjusts_stock_and_writes_count_transaction(self, test_session, test_engine):
        wh, prod, ledger = self._seed(test_session)

        # 用绑定到内存引擎的 get_db 替换 service 内的 get_db
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

        @contextlib.contextmanager
        def _get_db():
            db = SessionLocal()
            try:
                yield db
                db.commit()
            finally:
                db.close()

        svc = InventoryService()
        with patch("app.services.inventory_service.get_db", _get_db):
            result = svc.inventory_count(
                product_id=prod.id,
                warehouse_id=wh.id,
                actual_quantity=120,
                confirmed=True,
                operator="tester",
                remark="年末盘点",
            )

        assert result["success"] is True
        assert result["confirmed"] is True
        assert result["data"]["book_quantity"] == 100.0
        assert result["data"]["actual_quantity"] == 120.0
        assert result["data"]["diff"] == 20.0

        # 使 test_session 身份映射过期，重新从库中读取最新值
        test_session.expire_all()

        # 验证台账已调整为实盘数量
        updated = (
            test_session.query(InventoryLedger).filter(InventoryLedger.id == ledger.id).first()
        )
        assert float(updated.quantity) == 120.0
        # available_quantity 也按 diff 同步调整（90 + 20）
        assert float(updated.available_quantity) == 110.0

        # 验证写入一条 count 流水
        txns = (
            test_session.query(InventoryTransaction)
            .filter(InventoryTransaction.ledger_id == ledger.id)
            .all()
        )
        assert len(txns) == 1
        txn = txns[0]
        assert txn.transaction_type == "count"
        assert float(txn.quantity) == 20.0
        assert float(txn.before_quantity) == 100.0
        assert float(txn.after_quantity) == 120.0
        assert txn.reference_type == "inventory_count"
        assert txn.operator == "tester"

    def test_confirmed_negative_diff_reduces_stock(self, test_session, test_engine):
        """实盘小于账面（盘亏）时 diff 为负，库存下调并写负值 count 流水。"""
        wh, prod, ledger = self._seed(test_session)

        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

        @contextlib.contextmanager
        def _get_db():
            db = SessionLocal()
            try:
                yield db
                db.commit()
            finally:
                db.close()

        svc = InventoryService()
        with patch("app.services.inventory_service.get_db", _get_db):
            result = svc.inventory_count(
                product_id=prod.id,
                warehouse_id=wh.id,
                actual_quantity=80,
                confirmed=True,
            )

        assert result["success"] is True
        assert result["data"]["diff"] == -20.0

        test_session.expire_all()

        updated = (
            test_session.query(InventoryLedger).filter(InventoryLedger.id == ledger.id).first()
        )
        assert float(updated.quantity) == 80.0
        assert float(updated.available_quantity) == 70.0

        txns = (
            test_session.query(InventoryTransaction)
            .filter(InventoryTransaction.ledger_id == ledger.id)
            .all()
        )
        assert len(txns) == 1
        assert float(txns[0].quantity) == -20.0


# ---------------------------------------------------------------------------
# query_transactions
# ---------------------------------------------------------------------------
class TestQueryTransactions:
    def test_wraps_get_inventory_transactions(self):
        """query_transactions 返回与 get_inventory_transactions 相同结构。"""
        svc = InventoryService()
        with patch.object(
            svc,
            "get_inventory_transactions",
            return_value={
                "success": True,
                "data": [],
                "total": 0,
                "page": 1,
                "per_page": 50,
            },
        ) as mock_get:
            result = svc.query_transactions(product_id=1, warehouse_id=2)
        mock_get.assert_called_once_with(product_id=1, warehouse_id=2)
        assert result["total"] == 0

    @patch("app.services.inventory_service.get_db")
    def test_filters_by_warehouse_id(self, mock_get_db):
        """多仓库场景下按 warehouse_id 过滤流水。"""
        mock_item = MagicMock()
        mock_item.__table__ = MagicMock()
        mock_item.__table__.columns = []
        mock_item.product = MagicMock(name="Product A")
        mock_item.warehouse = MagicMock(name="WH02")
        mock_item.location = MagicMock(name="B-1")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_item
        ]
        mock_db.query.return_value.filter.return_value.count.return_value = 1
        mock_get_db.return_value = mock_db

        svc = InventoryService()
        result = svc.query_transactions(warehouse_id=2)
        filter_call = mock_db.query.return_value.filter
        filter_call.assert_called()
        assert result["success"] is True
        assert result["total"] == 1
