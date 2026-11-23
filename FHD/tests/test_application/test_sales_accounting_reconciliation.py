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
    assert replay["success"] is False
    assert replay["code"] == "PAYMENT_RECEIPT_UNVERIFIED"
    assert replay["retryable"] is False
    assert verify(case, replay)["accepted"] is False
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(ReceivableAllocation).count() == db.query(JournalEntry).count() == 1
        assert db.get(SalesOrder, sales[2]["order_id"]).paid_amount == Decimal("100")


@pytest.mark.parametrize("action", ["invoice", "credit_note"])
def test_duplicate_posted_invoice_or_credit_note_cannot_certify_original_sale(sales, action):
    from app.domain.shared_services.accounting_services import create_journal_entry

    case = prepare(sales, action)
    output = effect(sales, case)
    assert verify(case, output)["accepted"]
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        original = db.get(JournalEntry, output["data"]["id"])
        duplicate = create_journal_entry(
            {
                "reference_type": original.reference_type,
                "reference_id": original.reference_id,
                "reversed_of_id": original.reversed_of_id,
                "credit_note_of_id": original.credit_note_of_id,
                "is_credit_note": original.is_credit_note,
                "lines": [
                    {
                        "account_code": line.account_code,
                        "debit": line.debit,
                        "credit": line.credit,
                        "partner_id": line.partner_id,
                    }
                    for line in original.lines
                ],
            },
            db=db,
        )
        assert duplicate["success"]
    assert verify(case, output)["accepted"] is False


def test_verified_credit_note_keeps_the_exact_original_customer_journal(sales):
    case = prepare(sales, "credit_note")
    output = effect(sales, case)
    assert verify(case, output)["accepted"]
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        reversal = db.get(JournalEntry, output["data"]["id"])
        original = db.get(JournalEntry, reversal.reversed_of_id)
        next(line for line in original.lines if line.account_code == "1122").partner_id = 99999
    assert verify(case, output)["accepted"] is False


def test_invoice_after_valid_credit_note_keeps_complete_original_pairs(sales):
    for _ in range(2):
        invoice_case = prepare(sales, "invoice")
        invoice_output = effect(sales, invoice_case)
        assert verify(invoice_case, invoice_output)["accepted"]
        credit_case = prepare(sales, "credit_note")
        credit_output = effect(sales, credit_case)
        assert verify(credit_case, credit_output)["accepted"]
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory() as db:
        assert db.query(JournalEntry).count() == 4


@pytest.mark.parametrize("corruption", ["partner", "empty_lines"])
def test_historical_invoice_pairs_must_match_the_original_journal_contract(sales, corruption):
    credit_case = prepare(sales, "credit_note")
    credit_output = effect(sales, credit_case)
    invoice_case = prepare(sales, "invoice")
    invoice_output = effect(sales, invoice_case)
    assert verify(invoice_case, invoice_output)["accepted"]
    actor = sales[0]
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        credit = db.get(JournalEntry, credit_output["data"]["id"])
        original = db.get(JournalEntry, credit.reversed_of_id)
        for entry in (original, credit):
            if corruption == "partner":
                next(line for line in entry.lines if line.account_code == "1122").partner_id = 99999
            else:
                entry.lines.clear()
    assert verify(invoice_case, invoice_output)["accepted"] is False


@pytest.mark.parametrize(
    "corruption", [None, "reference", "original", "original_not_posted", "partner", "duplicate"]
)
def test_original_finance_reversal_preserves_invoice_reconciliation(sales, corruption):
    from app.domain.shared_services.accounting_services import (
        create_journal_entry,
        journal_entry_reverse,
    )

    first_case = prepare(sales, "invoice")
    first = effect(sales, first_case)
    assert verify(first_case, first)["accepted"]
    actor = sales[0]
    with tenant_scope(actor.tenant_id):
        reversed_receipt = journal_entry_reverse(first["data"]["id"])
    assert reversed_receipt["success"], reversed_receipt
    second_case = prepare(sales, "invoice")
    second = effect(sales, second_case)
    assert second["success"], second
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        reversal = db.get(JournalEntry, reversed_receipt["data"]["id"])
        original = db.get(JournalEntry, first["data"]["id"])
        assert reversal.reference_type == "reversal"
        assert reversal.reference_id == reversal.reversed_of_id == original.id
        assert original.tenant_id == reversal.tenant_id == actor.tenant_id
        assert original.reversed_at and reversal.reversed_at is None
        assert (
            reversal.debit_total
            == sum(line.debit for line in reversal.lines)
            == original.debit_total
        )
        assert (
            reversal.credit_total
            == sum(line.credit for line in reversal.lines)
            == original.credit_total
        )
        if corruption == "reference":
            reversal.reference_id = second["data"]["id"]
        elif corruption == "original":
            reversal.reversed_of_id = second["data"]["id"]
        elif corruption == "original_not_posted":
            original.status = "draft"
        elif corruption == "partner":
            next(line for line in reversal.lines if line.account_code == "1122").partner_id = 99999
        elif corruption == "duplicate":
            duplicate = create_journal_entry(
                {
                    "reference_type": reversal.reference_type,
                    "reference_id": reversal.reference_id,
                    "reversed_of_id": reversal.reversed_of_id,
                    "lines": [
                        {
                            "account_code": line.account_code,
                            "debit": line.debit,
                            "credit": line.credit,
                            "partner_id": line.partner_id,
                        }
                        for line in reversal.lines
                    ],
                },
                db=db,
            )
            assert duplicate["success"]
    assert second["data"]["id"] != first["data"]["id"]
    assert verify(second_case, second)["accepted"] is (corruption is None)
    if corruption is None:
        credit_case = prepare(sales, "credit_note")
        credit = effect(sales, credit_case)
        assert verify(credit_case, credit)["accepted"]
