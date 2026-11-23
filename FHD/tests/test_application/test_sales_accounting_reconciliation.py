"""Real committed accounting rows must prove the original customer's receipt."""

from decimal import Decimal

import pytest
from sqlalchemy import event

from app.db.models import Customer, JournalEntry, ReceivableAllocation, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_sales_verification_readback import (
    effect,
    prepare,
    verify,
)
from tests.test_application.test_sales_verification_readback import (
    sales as sales,
)


@pytest.mark.parametrize("action", ["invoice", "payment", "credit_note"])
@pytest.mark.parametrize("receivable", [True, False])
def test_journal_for_another_customer_cannot_certify_original_sale(sales, action, receivable):
    case = prepare(sales, action)
    output = effect(sales, case)
    assert verify(case, output)["accepted"]
    actor = sales[0]
    entry_id = output["data"]["journal_entry_id"] if action == "payment" else output["data"]["id"]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        entry = db.get(JournalEntry, entry_id)
        line = next(line for line in entry.lines if (line.account_code == "1122") == receivable)
        line.partner_id = 99999
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert verify(case, output)["accepted"] is False
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_payment_without_partner_binds_original_order_customer(sales):
    case = prepare(sales, "payment")
    output = effect(sales, case)
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        order = db.get(SalesOrder, sales[2]["order_id"])
        entry = db.get(JournalEntry, output["data"]["journal_entry_id"])
        receivable = next(line for line in entry.lines if line.account_code == "1122")
        assert receivable.partner_id == order.customer_id
        assert receivable.partner_name == order.customer_name
    assert verify(case, output)["accepted"]


def test_payment_rejects_another_customer_before_posting(sales):
    actor, service, ids = sales
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        customer = Customer(customer_name="Different payment customer")
        db.add(customer)
        db.flush()
        wrong_partner = customer.id
    with tenant_scope(actor.tenant_id):
        rejected = service.payment(ids["order_id"], 100, partner_id=wrong_partner)
    assert rejected["success"] is False
    assert rejected["code"] == "PAYMENT_PARTNER_MISMATCH"
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(JournalEntry).count() == 0
        assert db.query(ReceivableAllocation).count() == 0
        assert db.get(SalesOrder, ids["order_id"]).paid_amount == 0


@pytest.mark.parametrize("extra", ["missing_journal", "duplicate_journal", "other_reference"])
def test_aggregate_paid_amount_needs_each_original_payment_journal(sales, extra):
    case = prepare(sales, "payment")
    output = effect(sales, case)
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        original = db.get(ReceivableAllocation, output["data"]["id"])
        db.add(
            ReceivableAllocation(
                sales_order_id=original.sales_order_id,
                journal_entry_id=None if extra == "missing_journal" else original.journal_entry_id,
                line_id=original.line_id,
                amount=100,
                allocated_amount=100,
                status="partial",
                reference_type="adjustment" if extra == "other_reference" else "payment",
                reference_id=original.sales_order_id,
            )
        )
        db.get(SalesOrder, original.sales_order_id).paid_amount = Decimal("200")
    assert verify(case, output)["accepted"] is False


def test_legacy_unbound_payment_is_not_replayed_or_silently_certified(sales):
    case = prepare(sales, "payment", idempotency_key="legacy-original-payment")
    output = effect(sales, case)
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        entry = db.get(JournalEntry, output["data"]["journal_entry_id"])
        next(line for line in entry.lines if line.account_code == "1122").partner_id = None
    replay = effect(sales, case)
    assert replay["idempotent"] is True
    assert replay["data"]["id"] == output["data"]["id"]
    assert verify(case, replay)["accepted"] is False
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(ReceivableAllocation).count() == db.query(JournalEntry).count() == 1
        assert db.get(SalesOrder, sales[2]["order_id"]).paid_amount == Decimal("100")
