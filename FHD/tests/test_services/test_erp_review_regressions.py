"""Business regressions for the integration candidate's reviewed ERP paths."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app.db.models import InventoryLedger, StorageLocation
from app.domain.shared_services.inventory_movements import _move_available
from app.domain.shared_services.inventory_orders import _order_ledger_cas
from app.domain.shared_services.inventory_service import InventoryService
from app.domain.shared_services.tools_workflow_erp import (
    _registered_router_customers,
    _registered_router_inventory,
)
from tests.test_services.test_fulfillment_service import _seed_order
from tests.test_services.test_fulfillment_service import env as env


def test_fractional_receipts_can_be_withdrawn_and_reserved(env):
    order, item, product, warehouse = _seed_order(env, stock=0.1)
    svc = InventoryService()
    assert svc.inventory_in(product.id, warehouse.id, 0.2)["success"]
    withdrawn = svc.inventory_out(product.id, warehouse.id, 0.1)
    assert withdrawn["success"], withdrawn
    reserved = svc.reserve_for_order(
        product.id,
        warehouse.id,
        0.1,
        sales_order_id=order.id,
        sales_order_item_id=item.id,
    )
    assert reserved["success"], reserved
    with env["test_db"]() as db:
        ledger = db.query(InventoryLedger).one()
        assert (ledger.quantity, ledger.available_quantity, ledger.reserved_quantity) == (
            Decimal("0.2"),
            Decimal("0.1"),
            Decimal("0.1"),
        )


@pytest.mark.parametrize("order_movement", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_sqlite_balance_cas_accepts_old_residue_but_rejects_changed_stock(
    env,
    order_movement,
    stale,
):
    _seed_order(env, stock=0.1)
    with env["test_db"]() as db:
        db.execute(
            text(
                "UPDATE inventory_ledger SET quantity = quantity + 0.2, "
                "available_quantity = available_quantity + 0.2"
            )
        )
        db.expire_all()
        ledger = db.query(InventoryLedger).one()
        assert ledger.quantity == Decimal("0.3000")
        if stale:
            db.execute(
                text("UPDATE inventory_ledger SET quantity = 0.3001, available_quantity = 0.3001")
            )
        if order_movement:
            success = _order_ledger_cas(
                db,
                ledger,
                physical_delta=Decimal("0"),
                available_delta=Decimal("-0.1"),
                reserved_delta=Decimal("0.1"),
                now=datetime.now(),
            )
        else:
            success = _move_available(db, ledger, Decimal("0.1"), datetime.now())
        assert success is not stale
        db.refresh(ledger)
        assert ledger.quantity == Decimal("0.3001" if stale else "0.3" if order_movement else "0.4")


def test_release_uses_the_reserved_location_without_touching_another_order(env):
    order, item, product, warehouse = _seed_order(env)
    with env["test_db"]() as db:
        location = StorageLocation(warehouse_id=warehouse.id, code="SECOND", status="active")
        db.add(location)
        db.flush()
        location_id = location.id
    svc = InventoryService()
    assert svc.inventory_in(product.id, warehouse.id, 5, location_id=location_id)["success"]
    identity = {"sales_order_id": order.id, "sales_order_item_id": item.id}
    assert svc.reserve_for_order(product.id, warehouse.id, 3, **identity)["success"]
    reserved = svc.reserve_for_order(
        product.id,
        warehouse.id,
        2,
        location_id=location_id,
        **identity,
    )
    assert reserved["success"]
    with env["test_db"]() as db:
        released = svc.release_for_order(
            product.id,
            warehouse.id,
            2,
            location_id=location_id,
            db=db,
            **identity,
        )
        assert released["success"], released
        assert released["ledger_id"] == reserved["ledger_id"]
        rows = {row.location_id: row for row in db.query(InventoryLedger)}
        assert rows[None].reserved_quantity == 3
        assert rows[location_id].reserved_quantity == 0
        assert rows[location_id].available_quantity == 5


def test_customer_clear_reads_every_supported_page_before_deleting(monkeypatch):
    svc = Mock()
    customers = [{"id": n} for n in range(1, 206)]

    def listing(*, keyword, page, per_page):
        if per_page > 100:
            return {"success": False, "error_code": "invalid_pagination", "data": []}
        return {
            "success": True,
            "total": len(customers),
            "data": customers[(page - 1) * per_page : page * per_page],
        }

    svc.get_all.side_effect = listing
    svc.batch_delete.return_value = {"success": True, "deleted_count": 205}
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: svc)
    context = {"run_id": "approved-clear"}
    result = _registered_router_customers("clear", {}, context, "normal", "")
    assert result == {"success": True, "deleted_count": 205}
    assert [call.kwargs["page"] for call in svc.get_all.call_args_list] == [1, 2, 3]
    svc.batch_delete.assert_called_once_with(
        list(range(1, 206)), force=True, runtime_context=context
    )


def test_customer_clear_listing_failure_does_not_delete_or_report_empty(monkeypatch):
    svc = Mock()
    svc.batch_delete.return_value = {"success": True, "deleted_count": 100}
    failure = {"success": False, "error_code": "database_unavailable", "data": []}
    svc.get_all.side_effect = [
        {"success": True, "data": [{"id": n} for n in range(1, 101)], "total": 120},
        failure,
    ]
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: svc)
    result = _registered_router_customers("clear", {}, {}, "normal", "")
    assert result["success"] is False
    assert result["error_code"] == "database_unavailable"
    svc.batch_delete.assert_not_called()


def test_registered_inventory_count_preserves_preview_baseline_and_stale_rejection(env):
    _, _, product, warehouse = _seed_order(env)
    params = {"product_id": product.id, "warehouse_id": warehouse.id, "actual_quantity": 99}
    preview = _registered_router_inventory("inventory_count", params, {}, "normal", "")
    assert preview["success"], preview
    params.update(confirmed=True, expected_baseline_version=preview["data"]["baseline_version"])
    posted = _registered_router_inventory("inventory_count", params, {}, "normal", "")
    assert posted["success"], posted
    stale = _registered_router_inventory("inventory_count", params, {}, "normal", "")
    assert not stale["success"]
    assert stale["error_code"] == "inventory_count_stale"
