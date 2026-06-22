"""Comprehensive tests for app.application.shipment_app_service — coverage ramp.

Extends the existing basic tests with full coverage of all public methods,
error paths, edge cases, and conditional branches.
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.shipment_app_service import ShipmentApplicationService
from app.domain.shipment.aggregates import Shipment, ShipmentItem
from app.legacy.domain.legacy_vo import ContactInfo, Money, Quantity

# ---------------------------------------------------------------------------
# Dummy implementations for testing (reuse pattern from existing test)
# ---------------------------------------------------------------------------


class DummyRepository:
    """In-memory shipment repository for testing."""

    def __init__(self):
        self._items: dict[int, Shipment] = {}
        self._id = 1

    def save(self, shipment: Shipment) -> Shipment:
        if shipment.id is None:
            shipment.id = self._id
            self._id += 1
        self._items[shipment.id] = shipment
        return shipment

    def find_by_id(self, shipment_id: int):
        return self._items.get(shipment_id)

    def find_all(self, page: int = 1, per_page: int = 20):
        return list(self._items.values())

    def find_by_unit(self, unit_name: str):
        return [s for s in self._items.values() if s.purchase_unit_name == unit_name]

    def count(self) -> int:
        return len(self._items)

    def delete(self, shipment_id: int) -> bool:
        return self._items.pop(shipment_id, None) is not None


class DummyDocumentGenerator:
    def __init__(self, success: bool = True):
        self._success = success
        self.call_count = 0

    def generate(self, unit_name: str, products: list, **kwargs) -> dict:
        self.call_count += 1
        if self._success:
            return {
                "success": True,
                "doc_name": f"{unit_name}_shipment.xlsx",
                "file_path": f"/tmp/{unit_name}_shipment.xlsx",
                "purchase_unit": unit_name,
                "unit_id": 1,
                "parsed_products": products,
            }
        return {"success": False, "message": "生成失败"}


class DummyRecordStore:
    def __init__(self, *, record_id: int | None = 42):
        self.recorded: list[dict] = []
        self._record_id = record_id

    def record_document_generation(self, **kwargs) -> dict:
        self.recorded.append(kwargs)
        return {"record_id": self._record_id}


class DummyRecordQuery:
    def __init__(self, data: list[dict] | None = None):
        self._data = data or []

    def query_shipments(self, **kwargs) -> dict:
        return {
            "success": True,
            "data": self._data,
            "total": len(self._data),
            "page": kwargs.get("page", 1),
            "per_page": kwargs.get("per_page", 20),
        }

    def search_shipments(self, query: str) -> list[dict]:
        return self._data

    def get_shipment_by_id(self, order_number: str) -> dict | None:
        for d in self._data:
            if d.get("order_number") == order_number:
                return d
        return None

    def get_latest_shipments(self, limit: int = 10) -> list[dict]:
        return self._data[:limit]

    def get_shipment_records(self, unit_name=None, *, limit=100) -> list[dict]:
        return self._data[:limit]


class DummyRecordCommand:
    def __init__(self):
        self.cleared_units: list[str] = []
        self.all_cleared = False
        self.updated: list[dict] = []
        self.deleted_ids: list[int] = []

    def clear_by_unit(self, purchase_unit: str) -> dict:
        self.cleared_units.append(purchase_unit)
        return {"success": True, "cleared": True}

    def clear_all(self) -> dict:
        self.all_cleared = True
        return {"success": True, "cleared": True}

    def update_record(self, record_id: int, *, unit_name=None, date=None, fields=None) -> dict:
        self.updated.append(
            {"record_id": record_id, "unit_name": unit_name, "date": date, "fields": fields}
        )
        return {"success": True, "record_id": record_id}

    def delete_record(self, record_id: int) -> dict:
        self.deleted_ids.append(record_id)
        return {"success": True, "deleted": True}


class DummyPurchaseUnitQuery:
    def __init__(self, units: list[str] | None = None):
        self._units = units or ["单位A", "单位B"]

    def list_purchase_units(self) -> list[str]:
        return self._units


@pytest.fixture(autouse=True)
def _noop_shipment_hooks(monkeypatch):
    monkeypatch.setattr("app.infrastructure.mods.hooks.trigger", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# create_shipment
# ---------------------------------------------------------------------------


class TestCreateShipment:
    def test_create_shipment_success(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        items = [
            {
                "product_name": "产品A",
                "model_number": "9803",
                "quantity_tins": 3,
                "tin_spec": 20.0,
                "unit_price": 10.0,
                "amount": 600.0,
            }
        ]
        result = svc.create_shipment(
            unit_name="测试单位",
            items_data=items,
            contact_person="张三",
            contact_phone="13800138000",
        )
        assert result["success"] is True
        assert result["shipment"]["purchase_unit"] == "测试单位"
        assert len(result["shipment"]["items"]) == 1

    def test_create_shipment_invalid_no_items(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        result = svc.create_shipment(unit_name="测试单位", items_data=[])
        assert result["success"] is False
        assert "无效" in result["message"]

    def test_create_shipment_invalid_no_unit_name(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        items = [{"product_name": "产品A", "quantity_tins": 1}]
        result = svc.create_shipment(unit_name="", items_data=items)
        assert result["success"] is False

    def test_create_shipment_with_multiple_items(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        items = [
            {
                "product_name": "产品A",
                "quantity_tins": 3,
                "tin_spec": 20.0,
                "unit_price": 10.0,
                "amount": 600.0,
            },
            {
                "product_name": "产品B",
                "quantity_tins": 2,
                "tin_spec": 10.0,
                "unit_price": 20.0,
                "amount": 400.0,
            },
        ]
        result = svc.create_shipment(unit_name="测试单位", items_data=items)
        assert result["success"] is True
        assert len(result["shipment"]["items"]) == 2

    def test_create_shipment_skips_invalid_item(self):
        """Items with empty product_name are skipped (ValueError from ShipmentItem)."""
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        items = [
            {"product_name": "", "quantity_tins": 1},  # invalid: empty name
            {
                "product_name": "产品A",
                "quantity_tins": 1,
                "tin_spec": 10.0,
                "unit_price": 5.0,
                "amount": 50.0,
            },
        ]
        result = svc.create_shipment(unit_name="测试单位", items_data=items)
        assert result["success"] is True
        assert len(result["shipment"]["items"]) == 1

    def test_create_shipment_recoverable_error(self):
        repo = MagicMock()
        repo.save.side_effect = RuntimeError("DB connection lost")
        svc = ShipmentApplicationService(repository=repo)
        items = [
            {
                "product_name": "产品A",
                "quantity_tins": 1,
                "tin_spec": 10.0,
                "unit_price": 5.0,
                "amount": 50.0,
            }
        ]
        result = svc.create_shipment(unit_name="测试单位", items_data=items)
        assert result["success"] is False
        assert "创建失败" in result["message"]

    def test_create_shipment_hook_failure_does_not_block(self, monkeypatch):
        """Hook trigger failure should not block shipment creation."""
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        items = [
            {
                "product_name": "产品A",
                "quantity_tins": 1,
                "tin_spec": 10.0,
                "unit_price": 5.0,
                "amount": 50.0,
            }
        ]
        with patch("app.infrastructure.mods.hooks.trigger", side_effect=RuntimeError("hook fail")):
            result = svc.create_shipment(unit_name="测试单位", items_data=items)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# get_shipment / list_shipments
# ---------------------------------------------------------------------------


class TestGetShipment:
    def test_get_shipment_by_id(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        saved = repo.save(Shipment.create(unit_name="测试单位"))
        result = svc.get_shipment(shipment_id=saved.id)
        assert result is not None
        assert result.purchase_unit_name == "测试单位"

    def test_get_shipment_not_found(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        result = svc.get_shipment(shipment_id=999)
        assert result is None


class TestListShipments:
    def test_list_shipments(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        repo.save(Shipment.create(unit_name="单位A"))
        repo.save(Shipment.create(unit_name="单位B"))
        result = svc.list_shipments(page=1, per_page=20)
        assert result["success"] is True
        assert len(result["data"]) == 2

    def test_list_shipments_with_unit_name_filter(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        repo.save(Shipment.create(unit_name="单位A"))
        repo.save(Shipment.create(unit_name="单位B"))
        result = svc.list_shipments(unit_name="单位A")
        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_list_shipments_error(self):
        repo = MagicMock()
        repo.find_all.side_effect = RuntimeError("DB error")
        repo.count.side_effect = RuntimeError("DB error")
        svc = ShipmentApplicationService(repository=repo)
        result = svc.list_shipments()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# query_shipment_orders / search_orders / get_order / get_orders
# ---------------------------------------------------------------------------


class TestQueryShipmentOrders:
    def test_query_with_record_query(self):
        rq = DummyRecordQuery(data=[{"id": 1, "order_number": "ORD001"}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.query_shipment_orders(unit_name="单位A", page=1, per_page=20)
        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_query_without_record_query(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=None)
        result = svc.query_shipment_orders()
        assert result["success"] is False
        assert "record_query" in result["message"]


class TestSearchOrders:
    def test_search_with_record_query(self):
        rq = DummyRecordQuery(data=[{"id": 1}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.search_orders("test")
        assert len(result) == 1

    def test_search_without_record_query(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=None)
        result = svc.search_orders("test")
        assert result == []


class TestGetOrder:
    def test_get_order_found(self):
        rq = DummyRecordQuery(data=[{"order_number": "ORD001", "id": 1}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.get_order("ORD001")
        assert result is not None

    def test_get_order_not_found(self):
        rq = DummyRecordQuery(data=[])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.get_order("MISSING")
        assert result is None

    def test_get_order_without_record_query(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=None)
        result = svc.get_order("ORD001")
        assert result is None


class TestGetOrders:
    def test_get_orders_with_record_query(self):
        rq = DummyRecordQuery(data=[{"id": 1}, {"id": 2}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.get_orders(limit=10)
        assert len(result) == 2

    def test_get_orders_without_record_query(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=None)
        result = svc.get_orders()
        assert result == []

    def test_get_orders_limit(self):
        rq = DummyRecordQuery(data=[{"id": 1}, {"id": 2}, {"id": 3}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.get_orders(limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# get_purchase_units
# ---------------------------------------------------------------------------


class TestGetPurchaseUnits:
    def test_with_purchase_unit_query(self):
        puq = DummyPurchaseUnitQuery(units=["单位A", "单位B"])
        svc = ShipmentApplicationService(repository=DummyRepository(), purchase_unit_query=puq)
        result = svc.get_purchase_units()
        assert result == ["单位A", "单位B"]

    def test_without_purchase_unit_query(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), purchase_unit_query=None)
        result = svc.get_purchase_units()
        assert result == []


# ---------------------------------------------------------------------------
# clear_shipment_by_unit / clear_all_orders
# ---------------------------------------------------------------------------


class TestClearShipmentByUnit:
    def test_with_record_command(self):
        rc = DummyRecordCommand()
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=rc)
        result = svc.clear_shipment_by_unit("单位A")
        assert result["success"] is True
        assert "单位A" in rc.cleared_units

    def test_without_record_command(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=None)
        result = svc.clear_shipment_by_unit("单位A")
        assert result["success"] is False
        assert "record_command" in result["message"]


class TestClearAllOrders:
    def test_with_record_command(self):
        rc = DummyRecordCommand()
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=rc)
        result = svc.clear_all_orders()
        assert result["success"] is True
        assert rc.all_cleared is True

    def test_without_record_command(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=None)
        result = svc.clear_all_orders()
        assert result["success"] is False


# ---------------------------------------------------------------------------
# get_shipment_records / update_shipment_record / delete_shipment_record
# ---------------------------------------------------------------------------


class TestGetShipmentRecords:
    def test_with_record_query(self):
        rq = DummyRecordQuery(data=[{"id": 1}, {"id": 2}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.get_shipment_records()
        assert len(result) == 2

    def test_without_record_query(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=None)
        result = svc.get_shipment_records()
        assert result == []

    def test_with_unit_name(self):
        rq = DummyRecordQuery(data=[{"id": 1}])
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.get_shipment_records(unit_name="单位A")
        assert len(result) == 1


class TestUpdateShipmentRecord:
    def test_with_record_command(self):
        rc = DummyRecordCommand()
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=rc)
        result = svc.update_shipment_record(
            record_id=1,
            unit_name="单位A",
            date="2026-01-01",
            status="printed",
        )
        assert result["success"] is True
        assert len(rc.updated) == 1
        assert rc.updated[0]["fields"]["status"] == "printed"

    def test_without_record_command(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=None)
        result = svc.update_shipment_record(record_id=1)
        assert result["success"] is False

    def test_with_kwargs(self):
        rc = DummyRecordCommand()
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=rc)
        result = svc.update_shipment_record(
            record_id=1,
            custom_field="value",
        )
        assert result["success"] is True
        assert rc.updated[0]["fields"]["custom_field"] == "value"


class TestDeleteShipmentRecord:
    def test_with_record_command(self):
        rc = DummyRecordCommand()
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=rc)
        result = svc.delete_shipment_record(record_id=1)
        assert result["success"] is True
        assert 1 in rc.deleted_ids

    def test_without_record_command(self):
        svc = ShipmentApplicationService(repository=DummyRepository(), record_command=None)
        result = svc.delete_shipment_record(record_id=1)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# export_shipment_records
# ---------------------------------------------------------------------------


class TestExportShipmentRecords:
    def test_export_without_template(self, tmp_path):
        rq = DummyRecordQuery(
            data=[
                {
                    "id": 1,
                    "purchase_unit": "单位A",
                    "product_name": "产品A",
                    "model_number": "M1",
                    "quantity_kg": 100,
                    "quantity_tins": 5,
                    "tin_spec": "20kg",
                    "unit_price": 10,
                    "amount": 1000,
                    "status": "pending",
                    "created_at": datetime(2026, 1, 1),
                    "printed_at": None,
                    "printer_name": "",
                }
            ]
        )
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records()
            assert result["success"] is True
            assert result["count"] == 1
            assert result["file_path"].endswith(".xlsx")

    def test_export_with_unit_name(self, tmp_path):
        rq = DummyRecordQuery(
            data=[
                {
                    "id": 1,
                    "purchase_unit": "单位A",
                    "product_name": "产品A",
                    "model_number": "M1",
                    "quantity_kg": 100,
                    "quantity_tins": 5,
                    "tin_spec": "20kg",
                    "unit_price": 10,
                    "amount": 1000,
                    "status": "pending",
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
            ]
        )
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(unit_name="单位A")
            assert result["success"] is True

    def test_export_status_filter_printed(self, tmp_path):
        rq = DummyRecordQuery(
            data=[
                {
                    "id": 1,
                    "status": "printed",
                    "purchase_unit": "",
                    "product_name": "",
                    "model_number": "",
                    "quantity_kg": 0,
                    "quantity_tins": 0,
                    "tin_spec": "",
                    "unit_price": 0,
                    "amount": 0,
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
                {
                    "id": 2,
                    "status": "pending",
                    "purchase_unit": "",
                    "product_name": "",
                    "model_number": "",
                    "quantity_kg": 0,
                    "quantity_tins": 0,
                    "tin_spec": "",
                    "unit_price": 0,
                    "amount": 0,
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
            ]
        )
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(status_filter="printed")
            assert result["success"] is True
            assert result["count"] == 1

    def test_export_status_filter_pending(self, tmp_path):
        rq = DummyRecordQuery(
            data=[
                {
                    "id": 1,
                    "status": "printed",
                    "purchase_unit": "",
                    "product_name": "",
                    "model_number": "",
                    "quantity_kg": 0,
                    "quantity_tins": 0,
                    "tin_spec": "",
                    "unit_price": 0,
                    "amount": 0,
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
                {
                    "id": 2,
                    "status": "",
                    "purchase_unit": "",
                    "product_name": "",
                    "model_number": "",
                    "quantity_kg": 0,
                    "quantity_tins": 0,
                    "tin_spec": "",
                    "unit_price": 0,
                    "amount": 0,
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
            ]
        )
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(status_filter="pending")
            assert result["success"] is True
            assert result["count"] == 1

    def test_export_template_not_found(self, tmp_path):
        rq = DummyRecordQuery(data=[{"id": 1}])
        mock_template_svc = MagicMock()
        mock_template_svc.get_templates.return_value = {"templates": []}

        with (
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=mock_template_svc),
        ):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(template_id="99")
            assert result["success"] is False
            assert "模板不存在" in result["message"]

    def test_export_template_wrong_scope(self, tmp_path):
        rq = DummyRecordQuery(data=[{"id": 1}])
        mock_template_svc = MagicMock()
        mock_template_svc.get_templates.return_value = {
            "templates": [
                {
                    "id": "1",
                    "business_scope": "orders",
                    "template_type": "订单",
                    "path": "/tmp/t.xlsx",
                }
            ]
        }

        with (
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=mock_template_svc),
        ):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(template_id="1")
            assert result["success"] is False
            assert "不属于出货记录" in result["message"]

    def test_export_template_no_file_path(self, tmp_path):
        rq = DummyRecordQuery(data=[{"id": 1}])
        mock_template_svc = MagicMock()
        mock_template_svc.get_templates.return_value = {
            "templates": [
                {
                    "id": "1",
                    "business_scope": "shipmentRecords",
                    "template_type": "出货记录",
                    "path": "",
                    "file_path": "",
                }
            ]
        }

        with (
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=mock_template_svc),
        ):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(template_id="1")
            assert result["success"] is False
            assert "未绑定 Excel" in result["message"]

    def test_export_template_file_not_exists(self, tmp_path):
        rq = DummyRecordQuery(data=[{"id": 1}])
        mock_template_svc = MagicMock()
        mock_template_svc.get_templates.return_value = {
            "templates": [
                {
                    "id": "1",
                    "business_scope": "shipmentRecords",
                    "template_type": "出货记录",
                    "path": "/nonexistent/template.xlsx",
                }
            ]
        }

        with (
            patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)),
            patch("app.application.get_template_app_service", return_value=mock_template_svc),
            patch("os.path.exists", return_value=False),
        ):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(template_id="1")
            assert result["success"] is False
            assert "文件不存在" in result["message"]

    def test_export_error_handling(self, tmp_path):
        rq = MagicMock()
        rq.get_shipment_records.side_effect = RuntimeError("DB error")
        svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
        result = svc.export_shipment_records()
        assert result["success"] is False
        assert "导出失败" in result["message"]

    def test_export_with_empty_records(self, tmp_path):
        rq = DummyRecordQuery(data=[])
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records()
            assert result["success"] is True
            assert result["count"] == 0

    def test_export_status_filter_chinese_printed(self, tmp_path):
        rq = DummyRecordQuery(
            data=[
                {
                    "id": 1,
                    "status": "printed",
                    "purchase_unit": "",
                    "product_name": "",
                    "model_number": "",
                    "quantity_kg": 0,
                    "quantity_tins": 0,
                    "tin_spec": "",
                    "unit_price": 0,
                    "amount": 0,
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
            ]
        )
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(status_filter="已打印")
            assert result["success"] is True
            assert result["count"] == 1

    def test_export_status_filter_chinese_pending(self, tmp_path):
        rq = DummyRecordQuery(
            data=[
                {
                    "id": 1,
                    "status": "",
                    "purchase_unit": "",
                    "product_name": "",
                    "model_number": "",
                    "quantity_kg": 0,
                    "quantity_tins": 0,
                    "tin_spec": "",
                    "unit_price": 0,
                    "amount": 0,
                    "created_at": None,
                    "printed_at": None,
                    "printer_name": "",
                },
            ]
        )
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository(), record_query=rq)
            result = svc.export_shipment_records(status_filter="未打印")
            assert result["success"] is True
            assert result["count"] == 1


# ---------------------------------------------------------------------------
# set_order_sequence / reset_order_sequence
# ---------------------------------------------------------------------------


class TestOrderSequence:
    def test_set_order_sequence(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        result = svc.set_order_sequence(5)
        assert result["success"] is True
        assert result["sequence"] == 5

    def test_set_order_sequence_string(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        result = svc.set_order_sequence("10")
        assert result["success"] is True
        assert result["sequence"] == 10

    def test_reset_order_sequence(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        result = svc.reset_order_sequence()
        assert result["success"] is True
        assert result["sequence"] == 1


# ---------------------------------------------------------------------------
# download_shipment_order
# ---------------------------------------------------------------------------


class TestDownloadShipmentOrder:
    def test_file_exists(self, tmp_path):
        output_dir = tmp_path / "shipment_outputs"
        output_dir.mkdir()
        test_file = output_dir / "test.xlsx"
        test_file.write_text("data")

        with patch("app.utils.path_utils.get_app_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository())
            result = svc.download_shipment_order("test.xlsx")
            assert result["success"] is True
            assert result["file_path"] is not None

    def test_file_not_exists(self, tmp_path):
        with patch("app.utils.path_utils.get_app_data_dir", return_value=str(tmp_path)):
            svc = ShipmentApplicationService(repository=DummyRepository())
            result = svc.download_shipment_order("missing.xlsx")
            assert result["success"] is False
            assert "文件不存在" in result["message"]


# ---------------------------------------------------------------------------
# mark_as_printed
# ---------------------------------------------------------------------------


class TestMarkAsPrinted:
    def test_mark_as_printed_success(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        saved = repo.save(Shipment.create(unit_name="测试单位"))
        result = svc.mark_as_printed(shipment_id=saved.id, printer_name="HP-LaserJet")
        assert result["success"] is True
        assert "printed_at" in result

    def test_mark_as_printed_not_found(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        result = svc.mark_as_printed(shipment_id=999)
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_mark_as_printed_error(self):
        repo = MagicMock()
        repo.find_by_id.side_effect = RuntimeError("DB error")
        svc = ShipmentApplicationService(repository=repo)
        result = svc.mark_as_printed(shipment_id=1)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# cancel_shipment
# ---------------------------------------------------------------------------


class TestCancelShipment:
    def test_cancel_success(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        saved = repo.save(Shipment.create(unit_name="测试单位"))
        result = svc.cancel_shipment(shipment_id=saved.id)
        assert result["success"] is True

    def test_cancel_not_found(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        result = svc.cancel_shipment(shipment_id=999)
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_cancel_error(self):
        repo = MagicMock()
        repo.find_by_id.side_effect = RuntimeError("DB error")
        svc = ShipmentApplicationService(repository=repo)
        result = svc.cancel_shipment(shipment_id=1)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# delete_shipment
# ---------------------------------------------------------------------------


class TestDeleteShipment:
    def test_delete_success(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        saved = repo.save(Shipment.create(unit_name="测试单位"))
        result = svc.delete_shipment(shipment_id=saved.id)
        assert result["success"] is True
        assert repo.count() == 0

    def test_delete_not_found(self):
        repo = DummyRepository()
        svc = ShipmentApplicationService(repository=repo)
        result = svc.delete_shipment(shipment_id=999)
        assert result["success"] is False

    def test_delete_error(self):
        repo = MagicMock()
        repo.delete.side_effect = RuntimeError("DB error")
        svc = ShipmentApplicationService(repository=repo)
        result = svc.delete_shipment(shipment_id=1)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# calculate_totals
# ---------------------------------------------------------------------------


class TestCalculateTotals:
    def test_single_item(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        items = [{"quantity_tins": 5, "tin_spec": 20.0, "unit_price": 10.0}]
        result = svc.calculate_totals(items)
        assert result["total_tins"] == 5
        assert result["total_kg"] == 100.0
        assert result["total_amount"] == 1000.0

    def test_multiple_items(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        items = [
            {"quantity_tins": 5, "tin_spec": 20.0, "unit_price": 10.0},
            {"quantity_tins": 3, "tin_spec": 10.0, "unit_price": 20.0},
        ]
        result = svc.calculate_totals(items)
        assert result["total_tins"] == 8
        assert result["total_kg"] == 130.0
        assert result["total_amount"] == 1600.0

    def test_empty_items(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        result = svc.calculate_totals([])
        assert result["total_tins"] == 0
        assert result["total_kg"] == 0.0
        assert result["total_amount"] == 0.0

    def test_missing_fields_default_to_zero(self):
        svc = ShipmentApplicationService(repository=DummyRepository())
        items = [{}]
        result = svc.calculate_totals(items)
        assert result["total_tins"] == 0
        assert result["total_kg"] == 0.0
        assert result["total_amount"] == 0.0


# ---------------------------------------------------------------------------
# generate_shipment_document
# ---------------------------------------------------------------------------


class TestGenerateShipmentDocument:
    def test_without_document_generator(self):
        svc = ShipmentApplicationService(
            repository=DummyRepository(),
            document_generator=None,
        )
        result = svc.generate_shipment_document(
            unit_name="测试单位",
            products=[{"name": "产品A"}],
        )
        assert result["success"] is False
        assert "document_generator" in result["message"]

    def test_generate_success_with_record_store(self):
        doc_gen = DummyDocumentGenerator(success=True)
        record_store = DummyRecordStore(record_id=42)
        svc = ShipmentApplicationService(
            repository=DummyRepository(),
            document_generator=doc_gen,
            record_store=record_store,
        )
        products = [{"product_name": "产品A", "quantity_tins": 1}]
        result = svc.generate_shipment_document(
            unit_name="测试单位",
            products=products,
        )
        assert result["success"] is True
        assert result["record_id"] == 42
        assert result["order_id"] == 42
        assert len(record_store.recorded) == 1

    def test_generate_success_without_record_store(self):
        doc_gen = DummyDocumentGenerator(success=True)
        svc = ShipmentApplicationService(
            repository=DummyRepository(),
            document_generator=doc_gen,
            record_store=None,
        )
        result = svc.generate_shipment_document(
            unit_name="测试单位",
            products=[{"name": "产品A"}],
        )
        assert result["success"] is True
        assert "record_id" not in result

    def test_generate_failure_no_record_stored(self):
        doc_gen = DummyDocumentGenerator(success=False)
        record_store = DummyRecordStore()
        svc = ShipmentApplicationService(
            repository=DummyRepository(),
            document_generator=doc_gen,
            record_store=record_store,
        )
        result = svc.generate_shipment_document(
            unit_name="测试单位",
            products=[{"name": "产品A"}],
        )
        assert result["success"] is False
        assert len(record_store.recorded) == 0

    def test_generate_record_store_error_does_not_block(self):
        doc_gen = DummyDocumentGenerator(success=True)
        record_store = MagicMock()
        record_store.record_document_generation.side_effect = RuntimeError("write fail")
        svc = ShipmentApplicationService(
            repository=DummyRepository(),
            document_generator=doc_gen,
            record_store=record_store,
        )
        result = svc.generate_shipment_document(
            unit_name="测试单位",
            products=[{"name": "产品A"}],
        )
        assert result["success"] is True

    def test_generate_with_no_record_id(self):
        doc_gen = DummyDocumentGenerator(success=True)
        record_store = DummyRecordStore(record_id=None)
        svc = ShipmentApplicationService(
            repository=DummyRepository(),
            document_generator=doc_gen,
            record_store=record_store,
        )
        result = svc.generate_shipment_document(
            unit_name="测试单位",
            products=[{"name": "产品A"}],
        )
        assert result["success"] is True
        # No record_id/order_id should be set when record_id is None
        assert "record_id" not in result or result.get("record_id") is None
