"""Batch association checks stay constant-query and must not write on rejection.

Use the existing real SQLite + trusted tenant/role test fixture.
"""

import pytest
from sqlalchemy import event

from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_customer_cascade_authority import (
    deletion as deletion,
    snapshot,
)


@pytest.mark.parametrize("extra_customers", [0, 40])
def test_delete_preflight_aggregates_associations_without_n_plus_one(
    deletion, extra_customers
):
    _weak, actor, service = deletion
    with tenant_scope(7), actor.factory.begin() as db:
        extras = [
            PurchaseUnit(tenant_id=7, unit_name=f"Clean-{n:03d}")
            for n in range(extra_customers)
        ]
        db.add_all(extras)
        db.flush()
        customer_ids = [1, 2, 3, *(unit.id for unit in extras)]

    before = snapshot(actor)
    engine = actor.factory.kw["bind"]
    reads = []
    writes = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        kind = statement.lstrip().split(None, 1)[0].upper()
        if kind == "SELECT":
            reads.append(statement)
        elif kind in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with tenant_scope(7):
            denied = service.batch_delete(customer_ids)
    finally:
        event.remove(engine, "before_cursor_execute", observe)

    assert denied["success"] is False
    assert denied["deleted_count"] == 0
    assert [item["id"] for item in denied["affected_units"]] == [1, 2]
    assert [item["product_count"] for item in denied["affected_units"]] == [1, 1]
    assert [item["shipment_count"] for item in denied["affected_units"]] == [1, 1]
    # One customer lookup, one product GROUP BY, two shipment GROUP BYs.
    assert len(reads) <= 4, reads
    assert not writes, writes
    assert snapshot(actor) == before
