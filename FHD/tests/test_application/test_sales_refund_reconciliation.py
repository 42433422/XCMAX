"""Refund exclusion needs the original customer and an exact posted reversal."""

from decimal import Decimal

import pytest
from sqlalchemy import event

from app.application.sales.payment_verification import verified_sales_payment_total
from app.db.models import Customer, JournalEntry, ReceivableAllocation, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_sales_verification_readback import effect, prepare
from tests.test_application.test_sales_verification_readback import sales as sales


def _refund(sales):
    case = prepare(sales, "payment")
    payment = effect(sales, case)
    actor, service, ids = sales
    with tenant_scope(actor.tenant_id):
        refunded = service.refund(payment["data"]["id"])
    assert refunded["success"]
    return payment["data"]["id"], refunded["data"]["id"]


def _total(sales):
    actor, _, ids = sales
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        return verified_sales_payment_total(
            db, actor.tenant_id, db.get(SalesOrder, ids["order_id"])
        )


def test_refund_offsets_the_same_original_customer(sales):
    original_id, reversal_id = _refund(sales)
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        original = db.get(ReceivableAllocation, original_id)
        reversal = db.get(ReceivableAllocation, reversal_id)
        order = db.get(SalesOrder, original.sales_order_id)
        original_line = next(
            line for line in original.journal_entry.lines if line.account_code == "1122"
        )
        reverse_line = next(
            line for line in reversal.journal_entry.lines if line.account_code == "1122"
        )
        assert original_line.partner_id == reverse_line.partner_id == order.customer_id
        assert original_line.partner_name == reverse_line.partner_name
        assert original_line.credit == reverse_line.debit == Decimal("100")
    assert _total(sales) == 0
    with tenant_scope(actor.tenant_id):
        replay = sales[1].refund(original_id)
    assert replay["success"] and replay["idempotent"]
    assert replay["data"]["id"] == original_id
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(ReceivableAllocation).count() == db.query(JournalEntry).count() == 2


def test_refunded_status_without_a_real_reversal_is_unknown(sales):
    case = prepare(sales, "payment")
    payment = effect(sales, case)
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.get(ReceivableAllocation, payment["data"]["id"]).status = "refunded"
        order = db.get(SalesOrder, sales[2]["order_id"])
        order.paid_amount, order.payment_state = Decimal(0), "unpaid"
    assert _total(sales) is None
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with tenant_scope(actor.tenant_id):
            rejected = sales[1].refund(payment["data"]["id"])
        assert rejected["success"] is False
        assert rejected["code"] == "REFUND_RECEIPT_UNVERIFIED"
        assert rejected["retryable"] is False
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(ReceivableAllocation).count() == db.query(JournalEntry).count() == 1


@pytest.mark.parametrize("corruption", ["duplicate_payment_journal", "existing_reversal"])
def test_first_refund_rejects_inconsistent_original_ledger_before_posting(sales, corruption):
    actor, service, ids = sales
    if corruption == "existing_reversal":
        original_id, _ = _refund(sales)
    else:
        original_id = effect(sales, prepare(sales, "payment"))["data"]["id"]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        original = db.get(ReceivableAllocation, original_id)
        order = db.get(SalesOrder, ids["order_id"])
        original.status = order.payment_state = "partial"
        order.paid_amount = original.allocated_amount
        if corruption == "duplicate_payment_journal":
            db.add(
                ReceivableAllocation(
                    sales_order_id=original.sales_order_id,
                    journal_entry_id=original.journal_entry_id,
                    line_id=original.line_id,
                    amount=original.amount,
                    allocated_amount=original.allocated_amount,
                    status="partial",
                    reference_type="payment",
                    reference_id=original.sales_order_id,
                )
            )
            order.paid_amount += original.allocated_amount
        before = (
            db.query(ReceivableAllocation).count(),
            db.query(JournalEntry).count(),
            order.paid_amount,
            order.payment_state,
            original.status,
        )
    assert _total(sales) is None
    with tenant_scope(actor.tenant_id):
        rejected = service.refund(original_id)
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        order = db.get(SalesOrder, ids["order_id"])
        original = db.get(ReceivableAllocation, original_id)
        assert (
            db.query(ReceivableAllocation).count(),
            db.query(JournalEntry).count(),
            order.paid_amount,
            order.payment_state,
            original.status,
        ) == before
    assert rejected["success"] is False
    assert rejected["code"] == "REFUND_RECEIPT_UNVERIFIED"
    assert rejected["retryable"] is False
    assert _total(sales) is None


@pytest.mark.parametrize(
    "corruption",
    ["missing_original", "missing_reversal", "line", "partner", "reference", "duplicate"],
)
def test_refunded_receipt_requires_exact_original_reversal_evidence(sales, corruption):
    original_id, reversal_id = _refund(sales)
    assert _total(sales) == 0
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        original = db.get(ReceivableAllocation, original_id)
        reversal = db.get(ReceivableAllocation, reversal_id)
        if corruption == "missing_original":
            original.journal_entry_id = None
        elif corruption == "missing_reversal":
            reversal.journal_entry_id = None
        elif corruption == "line":
            reversal.line_id = original.line_id
        elif corruption == "partner":
            entry = db.get(JournalEntry, reversal.journal_entry_id)
            next(line for line in entry.lines if line.account_code == "1122").partner_id = 99999
        elif corruption == "reference":
            reversal.reference_id = original_id + 99
        else:
            db.add(
                ReceivableAllocation(
                    sales_order_id=original.sales_order_id,
                    journal_entry_id=reversal.journal_entry_id,
                    line_id=reversal.line_id,
                    amount=100,
                    allocated_amount=100,
                    status="refunded",
                    reference_type="reversal",
                    reference_id=original_id,
                    reversed_of_id=original_id,
                )
            )
        before = db.query(ReceivableAllocation).count(), db.query(JournalEntry).count()
    assert _total(sales) is None
    with tenant_scope(actor.tenant_id):
        rejected = sales[1].refund(original_id)
    assert rejected["success"] is False
    assert rejected["code"] == "REFUND_RECEIPT_UNVERIFIED"
    assert rejected["retryable"] is False
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert (db.query(ReceivableAllocation).count(), db.query(JournalEntry).count()) == before


def test_refund_reversal_id_cannot_replace_the_original_receipt(sales):
    _, reversal_id = _refund(sales)
    actor = sales[0]
    with tenant_scope(actor.tenant_id):
        rejected = sales[1].refund(reversal_id)
    assert rejected["success"] is False
    assert rejected["code"] == "REFUND_RECEIPT_UNVERIFIED"
    assert rejected["retryable"] is False
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(ReceivableAllocation).count() == db.query(JournalEntry).count() == 2


@pytest.mark.parametrize("customer", ["missing", "foreign_tenant"])
def test_new_payment_without_original_tenant_customer_is_rejected_before_posting(sales, customer):
    actor, service, ids = sales
    customer_id = None
    if customer == "foreign_tenant":
        with tenant_scope(actor.tenant_id + 1), actor.factory.begin() as db:
            other = Customer(customer_name="Other tenant's customer")
            db.add(other)
            db.flush()
            customer_id = other.id
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.get(SalesOrder, ids["order_id"]).customer_id = customer_id
    with tenant_scope(actor.tenant_id):
        rejected = service.payment(ids["order_id"], 100)
    assert rejected["success"] is False
    assert rejected["code"] == "PAYMENT_CUSTOMER_UNAVAILABLE"
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(JournalEntry).count() == db.query(ReceivableAllocation).count() == 0
        assert db.get(SalesOrder, ids["order_id"]).paid_amount == 0
