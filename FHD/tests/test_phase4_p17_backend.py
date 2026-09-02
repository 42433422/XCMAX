"""COVERAGE_RAMP Phase 4 round 17: inventory_service DB-mock paths (9.6%→)."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import (
    InventoryLedger,
    Product,
    StorageLocation,
    Warehouse,
)
from app.services.inventory_service import InventoryService


def _fluent(*, first=None, all_=None, count_=0) -> MagicMock:
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "group_by"):
        getattr(q, attr).return_value = q
    q.first.return_value = first
    q.all.return_value = list(all_ or [])
    q.count.return_value = count_
    return q


@contextmanager
def _fake_db(session):
    yield session


def _session(queries=None) -> MagicMock:
    session = MagicMock()
    if queries is not None:
        session.query.side_effect = list(queries)
    return session


def _patch_db(session):
    return patch("app.services.inventory_service.get_db", lambda: _fake_db(session))


class _Col:
    def __init__(self, name: str) -> None:
        self.name = name


class _Table:
    def __init__(self, names) -> None:
        self.columns = [_Col(n) for n in names]


class _FakeRow:
    """Lightweight stand-in for an ORM row: has __table__.columns + plain attrs.

    Avoids SQLAlchemy relationship backref machinery when assigning .product etc.
    """

    def __init__(self, columns: dict, **rel) -> None:
        self.__table__ = _Table(list(columns))
        for k, v in columns.items():
            setattr(self, k, v)
        for k, v in rel.items():
            setattr(self, k, v)


@pytest.fixture
def svc() -> InventoryService:
    return InventoryService()


# ---------------------------------------------------------------------------
# static helpers
# ---------------------------------------------------------------------------


def test_decimal_to_float() -> None:
    assert InventoryService._decimal_to_float(Decimal("1.5")) == 1.5
    assert InventoryService._decimal_to_float(3) == 3
    assert InventoryService._decimal_to_float(None) is None


def test_model_to_dict_none_and_real() -> None:
    assert InventoryService._model_to_dict(None) == {}
    wh = Warehouse(code="W1", name="主仓")
    d = InventoryService._model_to_dict(wh)
    assert d["code"] == "W1"
    assert d["name"] == "主仓"


# ---------------------------------------------------------------------------
# warehouses
# ---------------------------------------------------------------------------


def test_get_warehouses_empty(svc: InventoryService) -> None:
    s = _session([_fluent(all_=[])])
    with _patch_db(s):
        out = svc.get_warehouses()
    assert out["success"] is True
    assert out["count"] == 0


def test_get_warehouses_with_status(svc: InventoryService) -> None:
    s = _session([_fluent(all_=[Warehouse(code="W1", name="A")])])
    with _patch_db(s):
        out = svc.get_warehouses(status="active")
    assert out["count"] == 1


def test_get_warehouse_found_and_missing(svc: InventoryService) -> None:
    s = _session([_fluent(first=Warehouse(id=1, code="W1", name="A"))])
    with _patch_db(s):
        out = svc.get_warehouse(1)
    assert out["success"] is True
    s2 = _session([_fluent(first=None)])
    with _patch_db(s2):
        assert svc.get_warehouse(99)["success"] is False


def test_create_warehouse_success(svc: InventoryService) -> None:
    s = _session()
    with _patch_db(s):
        out = svc.create_warehouse({"code": "W2", "name": "新仓"})
    assert out["success"] is True
    s.add.assert_called_once()
    s.commit.assert_called_once()


def test_create_warehouse_error(svc: InventoryService) -> None:
    s = _session()
    s.commit.side_effect = RuntimeError("db down")
    with _patch_db(s):
        out = svc.create_warehouse({"code": "W3", "name": "X"})
    assert out["success"] is False
    s.rollback.assert_called_once()


def test_update_warehouse_not_found(svc: InventoryService) -> None:
    s = _session([_fluent(first=None)])
    with _patch_db(s):
        assert svc.update_warehouse(1, {"name": "x"})["success"] is False


def test_update_warehouse_success(svc: InventoryService) -> None:
    s = _session([_fluent(first=Warehouse(id=1, code="W1", name="A"))])
    with _patch_db(s):
        out = svc.update_warehouse(1, {"name": "改名", "bogus_field": "ignored"})
    assert out["success"] is True
    assert out["data"]["name"] == "改名"


def test_delete_warehouse_not_found(svc: InventoryService) -> None:
    s = _session([_fluent(first=None)])
    with _patch_db(s):
        assert svc.delete_warehouse(1)["success"] is False


def test_delete_warehouse_success(svc: InventoryService) -> None:
    s = _session([_fluent(first=Warehouse(id=1, code="W1", name="A"))])
    with _patch_db(s):
        out = svc.delete_warehouse(1)
    assert out["success"] is True


# ---------------------------------------------------------------------------
# storage locations
# ---------------------------------------------------------------------------


def test_get_storage_locations(svc: InventoryService) -> None:
    s = _session([_fluent(all_=[StorageLocation(id=1, warehouse_id=1, code="L1", name="位1")])])
    with _patch_db(s):
        out = svc.get_storage_locations(1, status="active")
    assert out["count"] == 1


def test_create_storage_location_success(svc: InventoryService) -> None:
    s = _session()
    with _patch_db(s):
        out = svc.create_storage_location(
            {"warehouse_id": 1, "code": "L1", "name": "位1", "max_capacity": Decimal("100")}
        )
    assert out["success"] is True


def test_update_storage_location_not_found(svc: InventoryService) -> None:
    s = _session([_fluent(first=None)])
    with _patch_db(s):
        assert svc.update_storage_location(1, {"name": "x"})["success"] is False


def test_update_storage_location_success(svc: InventoryService) -> None:
    s = _session([_fluent(first=StorageLocation(id=1, warehouse_id=1, code="L1", name="A"))])
    with _patch_db(s):
        out = svc.update_storage_location(
            1, {"name": "改", "max_capacity": Decimal("50"), "status": "active"}
        )
    assert out["success"] is True


# ---------------------------------------------------------------------------
# inventory queries
# ---------------------------------------------------------------------------


def test_get_inventory_with_items(svc: InventoryService) -> None:
    led = _FakeRow(
        {"id": 1, "product_id": 1, "warehouse_id": 1, "quantity": 5},
        product=SimpleNamespace(name="苹果", model_number="A1"),
        warehouse=SimpleNamespace(name="主仓"),
        location=SimpleNamespace(name="位1"),
    )
    s = _session([_fluent(all_=[led], count_=1)])
    with _patch_db(s):
        out = svc.get_inventory(warehouse_id=1, product_id=1, batch_no="B1", page=1, per_page=10)
    assert out["total"] == 1
    assert out["data"][0]["product_name"] == "苹果"
    assert out["data"][0]["warehouse_name"] == "主仓"


def test_get_inventory_summary(svc: InventoryService) -> None:
    row = SimpleNamespace(
        product_id=1,
        product_name="苹果",
        model_number="A1",
        total_quantity=Decimal("10"),
        total_available=Decimal("8"),
    )
    s = _session([_fluent(all_=[row])])
    with _patch_db(s):
        out = svc.get_inventory_summary(warehouse_id=1)
    assert out["data"][0]["total_quantity"] == 10.0
    assert out["data"][0]["total_available"] == 8.0


# ---------------------------------------------------------------------------
# inventory_in / out / transfer
# ---------------------------------------------------------------------------


def test_inventory_in_product_missing(svc: InventoryService) -> None:
    s = _session([_fluent(first=None)])
    with _patch_db(s):
        out = svc.inventory_in(product_id=1, warehouse_id=1, quantity=5)
    assert out["success"] is False
    assert "产品不存在" in out["message"]


def test_inventory_in_new_ledger(svc: InventoryService) -> None:
    product = Product(id=1, name="苹果", unit="箱", model_number="A1")
    s = _session([_fluent(first=product), _fluent(first=None)])
    with _patch_db(s):
        out = svc.inventory_in(
            product_id=1, warehouse_id=1, quantity=5, unit_price=2.0, batch_no="B1"
        )
    assert out["success"] is True
    assert out["data"]["quantity"] == 5


def test_inventory_in_existing_ledger(svc: InventoryService) -> None:
    product = Product(id=1, name="苹果", unit="箱", model_number="A1")
    ledger = InventoryLedger(id=9, product_id=1, warehouse_id=1, quantity=10, available_quantity=10)
    s = _session([_fluent(first=product), _fluent(first=ledger)])
    with _patch_db(s):
        out = svc.inventory_in(product_id=1, warehouse_id=1, quantity=5)
    assert out["success"] is True
    assert out["data"]["total_quantity"] == 15.0


def test_inventory_in_error(svc: InventoryService) -> None:
    product = Product(id=1, name="苹果", unit="箱", model_number="A1")
    s = _session([_fluent(first=product), _fluent(first=None)])
    s.commit.side_effect = RuntimeError("commit fail")
    with _patch_db(s):
        out = svc.inventory_in(product_id=1, warehouse_id=1, quantity=5)
    assert out["success"] is False
    s.rollback.assert_called_once()


def test_inventory_out_insufficient(svc: InventoryService) -> None:
    s = _session([_fluent(first=None)])
    with _patch_db(s):
        out = svc.inventory_out(product_id=1, warehouse_id=1, quantity=5)
    assert out["success"] is False


def test_inventory_out_success(svc: InventoryService) -> None:
    ledger = InventoryLedger(id=9, product_id=1, warehouse_id=1, quantity=10, available_quantity=10)
    s = _session([_fluent(first=ledger)])
    with _patch_db(s):
        out = svc.inventory_out(
            product_id=1, warehouse_id=1, quantity=4, batch_no="B1", location_id=2
        )
    assert out["success"] is True
    assert out["data"]["remaining_quantity"] == 6.0


def test_inventory_transfer_source_insufficient(svc: InventoryService) -> None:
    s = _session([_fluent(first=None)])
    with _patch_db(s):
        out = svc.inventory_transfer(
            product_id=1, from_warehouse_id=1, to_warehouse_id=2, quantity=5
        )
    assert out["success"] is False


def test_inventory_transfer_existing_target(svc: InventoryService) -> None:
    src = InventoryLedger(id=1, product_id=1, warehouse_id=1, quantity=10, available_quantity=10)
    src.unit = "箱"
    dst = InventoryLedger(id=2, product_id=1, warehouse_id=2, quantity=3, available_quantity=3)
    s = _session([_fluent(first=src), _fluent(first=dst)])
    with _patch_db(s):
        out = svc.inventory_transfer(
            product_id=1, from_warehouse_id=1, to_warehouse_id=2, quantity=4
        )
    assert out["success"] is True
    assert out["data"]["from_ledger_id"] == 1
    assert out["data"]["to_ledger_id"] == 2


def test_inventory_transfer_new_target(svc: InventoryService) -> None:
    src = InventoryLedger(id=1, product_id=1, warehouse_id=1, quantity=10, available_quantity=10)
    src.unit = "箱"
    s = _session([_fluent(first=src), _fluent(first=None)])
    with _patch_db(s):
        out = svc.inventory_transfer(
            product_id=1, from_warehouse_id=1, to_warehouse_id=2, quantity=4, batch_no="B1"
        )
    assert out["success"] is True


# ---------------------------------------------------------------------------
# transactions / alert
# ---------------------------------------------------------------------------


def test_get_inventory_transactions(svc: InventoryService) -> None:
    tx = _FakeRow(
        {"id": 1, "product_id": 1, "warehouse_id": 1, "transaction_type": "in"},
        product=SimpleNamespace(name="苹果"),
        warehouse=SimpleNamespace(name="主仓"),
        location=None,
    )
    s = _session([_fluent(all_=[tx], count_=1)])
    with _patch_db(s):
        out = svc.get_inventory_transactions(product_id=1, warehouse_id=1, transaction_type="in")
    assert out["total"] == 1
    assert out["data"][0]["product_name"] == "苹果"


def test_get_inventory_alert(svc: InventoryService) -> None:
    led = _FakeRow(
        {"id": 1, "product_id": 1, "warehouse_id": 1, "available_quantity": 0},
        product=SimpleNamespace(name="苹果", model_number="A1"),
    )
    s = _session([_fluent(all_=[led])])
    with _patch_db(s):
        out = svc.get_inventory_alert()
    assert out["success"] is True
    assert out["count"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
