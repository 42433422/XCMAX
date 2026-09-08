from unittest.mock import patch

import pytest

from app.services.inventory_service import InventoryService


@pytest.mark.parametrize("confirmed", ["false", "true", 1, 0, None, [], {}])
def test_count_requires_boolean_confirmation_before_database(confirmed):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_count(1, 1, 3, confirmed=confirmed)
    assert not result["success"]
    database.assert_not_called()


@pytest.mark.parametrize("quantity", [True, -1, None, float("nan"), float("inf")])
def test_count_rejects_invalid_quantity_before_database(quantity):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_count(1, 1, quantity, confirmed=True)
    assert not result["success"]
    database.assert_not_called()


def test_ai_count_string_false_does_not_become_confirmation():
    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    with patch("app.services.inventory_service.get_db") as database:
        result = _registered_router_inventory(
            "inventory_count",
            {"product_id": 1, "warehouse_id": 1, "actual_quantity": "3", "confirmed": "false"},
            {},
            "normal",
            "",
        )
    assert not result["success"]
    database.assert_not_called()


def test_ai_count_preview_and_confirmation_only_change_selected_location(tmp_path, monkeypatch):
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

    engine = create_engine(f"sqlite:///{tmp_path / 'count.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="产品"))
        db.add(Warehouse(id=1, tenant_id=1, name="仓库", code="W"))
        db.flush()
        for ident in (1, 2):
            db.add(StorageLocation(id=ident, tenant_id=1, warehouse_id=1, code=str(ident)))
        db.flush()
        for ident in (1, 2):
            db.add(
                InventoryLedger(
                    id=ident,
                    tenant_id=1,
                    product_id=1,
                    warehouse_id=1,
                    location_id=ident,
                    batch_no="B",
                    quantity=10,
                    available_quantity=8,
                    reserved_quantity=2,
                    unit="桶",
                )
            )
    params = {
        "product_id": 1,
        "warehouse_id": 1,
        "location_id": 2,
        "batch_no": "B",
        "actual_quantity": "7",
    }
    with tenant_scope(1):
        preview = _registered_router_inventory("inventory_count", params, {}, "normal", "")
    assert preview["success"] and preview["confirmed"] is False
    assert preview["data"]["diff"] == -3
    with factory() as db:
        assert [
            float(row.quantity) for row in db.query(InventoryLedger).order_by(InventoryLedger.id)
        ] == [10, 10]
        assert db.query(InventoryTransaction).count() == 0
    with tenant_scope(1):
        result = _registered_router_inventory(
            "inventory_count", {**params, "confirmed": True}, {}, "normal", ""
        )
    assert result["success"] and result["confirmed"] is True
    with factory() as db:
        rows = db.query(InventoryLedger).order_by(InventoryLedger.id).all()
        assert [
            (
                row.location_id,
                float(row.quantity),
                float(row.available_quantity),
                float(row.reserved_quantity),
            )
            for row in rows
        ] == [(1, 10, 8, 2), (2, 7, 5, 2)]
        receipt = db.query(InventoryTransaction).one()
        assert (receipt.ledger_id, receipt.location_id, receipt.batch_no) == (2, 2, "B")
        assert (
            float(receipt.before_quantity),
            float(receipt.after_quantity),
            float(receipt.quantity),
        ) == (10, 7, -3)
    with tenant_scope(1):
        readback = _registered_router_inventory(
            "query_transactions",
            {"product_id": 1, "warehouse_id": 1, "transaction_type": "count"},
            {},
            "normal",
            "",
        )
        assert readback["success"] and readback["total"] == 1
        row = readback["data"][0]
        assert row["transaction_type"] == "count"
        from datetime import datetime

        today = datetime.now().date().isoformat()
        dated = _registered_router_inventory(
            "query_transactions", {"start_date": today, "end_date": today}, {}, "normal", ""
        )
        assert dated["success"] and dated["total"] == 1
        assert row["location_id"] == 2 and row["batch_no"] == "B"
        assert float(row["quantity"]) == -3
        unrelated = _registered_router_inventory(
            "query_transactions",
            {"product_id": 1, "warehouse_id": 1, "transaction_type": "out"},
            {},
            "normal",
            "",
        )
        assert unrelated["success"] and unrelated["total"] == 0
    with tenant_scope(1):
        conflict = _registered_router_inventory(
            "inventory_count", {**params, "actual_quantity": 1, "confirmed": True}, {}, "normal", ""
        )
        assert conflict["error_code"] == "inventory_reserved_conflict"
        with factory() as db:
            stock = db.get(InventoryLedger, 2)
            assert float(stock.quantity) == 7 and float(stock.available_quantity) == 5
            assert db.query(InventoryTransaction).count() == 1
    with tenant_scope(2):
        foreign = _registered_router_inventory(
            "query_transactions", {"product_id": 1}, {}, "normal", ""
        )
        assert foreign["success"] and foreign["total"] == 0
    engine.dispose()


@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": "bad"},
        {"end_date": "2026-02-30"},
        {"start_date": "2026-09-10", "end_date": "2026-09-09"},
    ],
)
def test_ai_transaction_dates_rejected_before_database(dates):
    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    with patch("app.services.inventory_service.get_db") as database:
        result = _registered_router_inventory("query_transactions", dates, {}, "normal", "")
    assert not result["success"]
    database.assert_not_called()


@pytest.mark.parametrize("pagination", [
    {"page": 0}, {"page": True}, {"page": "1.5"}, {"page": "bad"},
    {"per_page": -1}, {"per_page": 1001}, {"per_page": False},
])
def test_ai_transaction_pagination_rejected_before_database(pagination):
    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    with patch("app.services.inventory_service.get_db") as database:
        result = _registered_router_inventory("query_transactions", pagination, {}, "normal", "")
    assert not result["success"]
    database.assert_not_called()
