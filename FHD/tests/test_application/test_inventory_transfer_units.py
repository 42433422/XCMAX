from unittest.mock import patch

import pytest

from app.services.inventory_service import InventoryService


@pytest.mark.parametrize("quantity", [0, -1, True, None, "bad", float("nan"), float("inf")])
def test_transfer_invalid_quantity_does_not_open_database(quantity):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_transfer(1, 1, 2, quantity)
    assert not result["success"]
    database.assert_not_called()


@pytest.mark.parametrize("target_unit", ["桶", "箱"])
def test_transfer_preserves_units_and_selects_exact_batch(tmp_path, monkeypatch, target_unit):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import (
        InventoryLedger,
        InventoryTransaction,
        Product,
        StorageLocation,
        Warehouse,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'transfer.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="产品", measurement_unit="桶"))
        db.add_all([Warehouse(id=i, tenant_id=1, name=str(i), code=str(i)) for i in (1, 2)])
        db.add(Warehouse(id=3, tenant_id=2, name="其他租户", code="OTHER"))
        db.flush()
        db.add(StorageLocation(id=1, tenant_id=1, warehouse_id=1, code="SOURCE"))
        db.add(StorageLocation(id=2, tenant_id=2, warehouse_id=3, code="FOREIGN"))
        for ident, warehouse, batch, unit in [
            (1, 1, None, "桶"),
            (2, 1, "B", "桶"),
            (3, 2, None, "桶"),
            (4, 2, "B", target_unit),
        ]:
            db.add(
                InventoryLedger(
                    id=ident,
                    tenant_id=1,
                    product_id=1,
                    warehouse_id=warehouse,
                    batch_no=batch,
                    quantity=10,
                    available_quantity=10,
                    reserved_quantity=0,
                    unit=unit,
                )
            )
    with tenant_scope(1):
        missing = InventoryService().inventory_transfer(1, 1, 999, 3, batch_no="B")
        assert not missing["success"]
        wrong_location = InventoryService().inventory_transfer(
            1, 1, 2, 3, batch_no="B", to_location_id=999
        )
        assert not wrong_location["success"]
        foreign = InventoryService().inventory_transfer(1, 1, 3, 3, batch_no="B")
        assert not foreign["success"]
        for location_id in (1, 2):
            wrong_owner = InventoryService().inventory_transfer(
                1, 1, 2, 3, batch_no="B", to_location_id=location_id
            )
            assert not wrong_owner["success"]
        with factory() as db:
            assert all(float(row.quantity) == 10 for row in db.query(InventoryLedger))
            assert db.query(InventoryTransaction).count() == 0
        result = InventoryService().inventory_transfer(1, 1, 2, 3, batch_no="B")
    with factory() as db:
        quantities = {row.id: float(row.quantity) for row in db.query(InventoryLedger)}
        transactions = db.query(InventoryTransaction).all()
        if target_unit == "桶":
            assert result["success"], result
            assert quantities == {1: 10, 2: 7, 3: 10, 4: 13}
            assert {(row.ledger_id, row.batch_no, float(row.quantity)) for row in transactions} == {
                (2, "B", -3),
                (4, "B", 3),
            }
        else:
            assert result["error_code"] == "inventory_unit_mismatch"
            assert quantities == {1: 10, 2: 10, 3: 10, 4: 10}
            assert transactions == []
    engine.dispose()


@pytest.mark.parametrize("location", [None, 1])
def test_transfer_to_same_stock_location_does_not_open_database(location):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_transfer(
            1, 2, 2, 3, from_location_id=location, to_location_id=location
        )
    assert not result["success"]
    database.assert_not_called()


def test_transfer_between_locations_in_same_warehouse(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import (
        InventoryLedger,
        InventoryTransaction,
        Product,
        StorageLocation,
        Warehouse,
    )
    from app.infrastructure.tenant_scope import tenant_scope
    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    engine = create_engine(f"sqlite:///{tmp_path / 'locations.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="产品", measurement_unit="桶"))
        db.add(Warehouse(id=1, tenant_id=1, name="仓库", code="W"))
        db.flush()
        db.add_all(
            [StorageLocation(id=i, tenant_id=1, warehouse_id=1, code=str(i)) for i in (1, 2)]
        )
        db.flush()
        db.add(
            InventoryLedger(
                product_id=1,
                tenant_id=1,
                warehouse_id=1,
                location_id=1,
                batch_no="B",
                quantity=10,
                available_quantity=8,
                reserved_quantity=2,
                unit="桶",
            )
        )
    with tenant_scope(1):
        result = _registered_router_inventory(
            "transfer",
            {
                "product_id": 1,
                "from_warehouse_id": 1,
                "to_warehouse_id": 1,
                "remark": "调整拣货库位",
                "from_location_id": 1,
                "to_location_id": 2,
                "batch_no": "B",
                "quantity": "3",
            },
            {},
            "normal",
            "",
        )
        assert result["success"], result
        with factory() as db:
            stocks = db.query(InventoryLedger).order_by(InventoryLedger.location_id).all()
            assert [
                (
                    row.location_id,
                    float(row.quantity),
                    float(row.available_quantity),
                    float(row.reserved_quantity),
                    row.unit,
                )
                for row in stocks
            ] == [(1, 7, 5, 2, "桶"), (2, 3, 3, 0, "桶")]
            receipts = db.query(InventoryTransaction).all()
            assert all("调整拣货库位" in row.remark for row in receipts)
            assert {
                (row.location_id, row.transaction_type, float(row.quantity)) for row in receipts
            } == {(1, "transfer_out", -3), (2, "transfer_in", 3)}
    engine.dispose()
