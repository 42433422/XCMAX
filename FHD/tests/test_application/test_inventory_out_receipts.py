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
        result = InventoryService().inventory_out(1, 1, 3)
    assert result["success"], result
    with factory() as db:
        ledger = db.query(InventoryLedger).one()
        transaction = db.query(InventoryTransaction).one()
        assert (float(ledger.quantity), float(ledger.available_quantity)) == (7, 5)
        assert (transaction.ledger_id, transaction.location_id, transaction.batch_no) == (1, 1, "B")
        assert (float(transaction.before_quantity), float(transaction.after_quantity)) == (10, 7)
    engine.dispose()
