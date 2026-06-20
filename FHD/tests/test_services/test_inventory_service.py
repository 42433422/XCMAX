"""Tests for app.services.inventory_service — coverage ramp."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.inventory_service import InventoryService


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
