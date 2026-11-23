"""Read original customer payments and their exact posted refund counterparts."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.application.agent_orchestrator.verification_transactions import _decimal, _journal
from app.db.models import ReceivableAllocation


def payment_receipt_journal(db, tenant, order, receipt):
    """The producer and independent reader share one original-receipt contract."""
    if (
        order is None
        or order.tenant_id != tenant
        or receipt.tenant_id != tenant
        or receipt.sales_order_id != order.id
        or receipt.reference_type != "payment"
        or receipt.reference_id != order.id
        or receipt.status not in {"partial", "paid", "refunded"}
        or receipt.reversed_of_id is not None
    ):
        return None
    amount = _decimal(receipt.allocated_amount)
    if amount <= 0 or _decimal(receipt.amount) != amount:
        return None
    entry = _journal(db, tenant, receipt.journal_entry_id, order.id, "payment", amount)
    return (
        entry
        if entry is not None
        and any(line.id == receipt.line_id and line.account_code == "1122" for line in entry.lines)
        else None
    )


def _refund_journal(db, tenant, order, receipt, reversal):
    amount = _decimal(receipt.allocated_amount)
    if (
        reversal is None
        or reversal.tenant_id != tenant
        or reversal.sales_order_id != order.id
        or reversal.status != "refunded"
        or reversal.reference_type != "reversal"
        or reversal.reference_id != receipt.id
        or reversal.reversed_of_id != receipt.id
        or _decimal(reversal.amount) != amount
        or _decimal(reversal.allocated_amount) != amount
    ):
        return None
    entry = _journal(
        db, tenant, reversal.journal_entry_id, order.id, "refund", amount, reference_id=receipt.id
    )
    return (
        entry
        if entry is not None
        and any(line.id == reversal.line_id and line.account_code == "1122" for line in entry.lines)
        else None
    )


def verified_sales_payment_total(db, tenant, order) -> Decimal | None:
    """Exclude refunded receipts only after their unique original reversal is proven."""
    from app.application.payment_service import _compute_status

    receipts = list(
        db.scalars(
            select(ReceivableAllocation).where(
                ReceivableAllocation.tenant_id == tenant,
                ReceivableAllocation.sales_order_id == order.id,
            )
        )
    )
    payments, reversals = [], {}
    for receipt in receipts:
        if receipt.reference_type == "payment":
            payments.append(receipt)
        elif receipt.reference_type == "reversal" and receipt.reversed_of_id not in reversals:
            reversals[receipt.reversed_of_id] = receipt
        else:
            return None
    total = Decimal(0)
    journals: set[int] = set()
    for receipt in payments:
        entry = payment_receipt_journal(db, tenant, order, receipt)
        if entry is None or entry.id in journals:
            return None
        journals.add(entry.id)
        if receipt.status == "refunded":
            reverse = _refund_journal(db, tenant, order, receipt, reversals.pop(receipt.id, None))
            if reverse is None or reverse.id in journals:
                return None
            journals.add(reverse.id)
        else:
            total += _decimal(receipt.allocated_amount)
    expected_state = _compute_status(total, _decimal(order.total_amount)) if total else "unpaid"
    if (
        reversals
        or total > _decimal(order.total_amount)
        or total != _decimal(order.paid_amount or 0)
        or order.payment_state != expected_state
    ):
        return None
    return total
