from unittest.mock import patch

import pytest

from app.services.inventory_service import InventoryService


@pytest.mark.parametrize("quantity", [0, -2, True, None, "bad", float("nan"), float("inf")])
def test_outbound_invalid_quantity_does_not_open_database(quantity):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_out(1, 1, quantity)
    assert not result["success"]
    database.assert_not_called()


def test_outbound_receipt_records_selected_stock_batch_and_location(tmp_path, monkeypatch):
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

    engine = create_engine(f"sqlite:///{tmp_path / 'out.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="产品"))
        db.add(Warehouse(id=1, tenant_id=1, name="仓库", code="W"))
        db.flush()
        db.add(StorageLocation(id=1, tenant_id=1, warehouse_id=1, code="A"))
        db.flush()
        db.add(
            InventoryLedger(
                id=1,
                tenant_id=1,
                product_id=1,
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
        from app.services.tools_workflow_registered_part01_part02 import (
            _registered_router_inventory,
        )

        result = _registered_router_inventory(
            "stock_out",
            {"product_id": 1, "warehouse_id": 1, "quantity": "3", "unit_price": "5"},
            {},
            "normal",
            "",
        )
    assert result["success"], result
    with factory() as db:
        ledger = db.query(InventoryLedger).one()
        transaction = db.query(InventoryTransaction).one()
        assert result["data"]["transaction_id"] == transaction.id
        assert float(transaction.unit_price) == 5
        assert float(transaction.total_amount) == 15
        assert (float(ledger.quantity), float(ledger.available_quantity)) == (7, 5)
        assert (transaction.ledger_id, transaction.location_id, transaction.batch_no) == (1, 1, "B")
        assert (float(transaction.before_quantity), float(transaction.after_quantity)) == (10, 7)
    engine.dispose()


@pytest.mark.parametrize("action", ["stock_out", "transfer"])
@pytest.mark.parametrize("quantity", [True, None, "bad", "NaN", "Infinity", 0, -1])
def test_ai_inventory_rejects_invalid_quantity_before_service(action, quantity):
    from unittest.mock import Mock

    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    service = Mock()
    with patch("app.application.inventory_app_service.InventoryAppService", return_value=service):
        result = _registered_router_inventory(action, {"quantity": quantity}, {}, "normal", "")
    assert not result["success"]
    service.inventory_out.assert_not_called()
    service.inventory_transfer.assert_not_called()


@pytest.mark.parametrize("method", ["inventory_in", "inventory_out"])
@pytest.mark.parametrize("price", [-1, True, float("nan"), float("inf"), "bad"])
def test_stock_movement_invalid_price_does_not_open_database(method, price):
    with patch("app.services.inventory_service.get_db") as database:
        result = getattr(InventoryService(), method)(1, 1, 3, unit_price=price)
    assert not result["success"]
    database.assert_not_called()


@pytest.mark.parametrize("method", ["inventory_in", "inventory_out"])
def test_stock_movement_rejects_overflowing_total_before_database(method):
    with patch("app.services.inventory_service.get_db") as database:
        result = getattr(InventoryService(), method)(1, 1, 1e200, unit_price=1e200)
    assert not result["success"]
    database.assert_not_called()


@pytest.mark.parametrize("action", ["stock_in", "stock_out"])
@pytest.mark.parametrize("price", ["bad", True, "NaN", "Infinity", -1])
def test_ai_movement_invalid_price_returns_business_error(action, price):
    from unittest.mock import Mock

    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    service = Mock()
    with patch("app.application.inventory_app_service.InventoryAppService", return_value=service):
        result = _registered_router_inventory(
            action, {"quantity": 3, "unit_price": price}, {}, "normal", ""
        )
    assert not result["success"]
    service.inventory_in.assert_not_called()
    service.inventory_out.assert_not_called()
