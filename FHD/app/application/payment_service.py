"""Transactional receipts and refunds.

Payment identity is an explicit, caller-stable ``idempotency_key``, not an amount
or a free-form reference. A call without a key denotes a new payment; retrying
clients must retain and reuse their key. Receipts, fingerprints and journal
entries share the caller's transaction. This service never commits it.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from app.db.models import ReceivableAllocation, SalesOrder
from app.db.models.receivable_allocation import (
    RECEIVABLE_STATUS_PAID,
    RECEIVABLE_STATUS_PARTIAL,
    RECEIVABLE_STATUS_REFUNDED,
    RECEIVABLE_STATUS_UNPAID,
)
from app.db.session import get_db
from app.infrastructure.tenant_scope import apply_tenant_filter
from app.services.accounting_services import create_journal_entry

CASH_ACCOUNT_CODE = "1001"
RECEIVABLE_ACCOUNT_CODE = "1122"
_MONEY_EPSILON = Decimal("0.005")
_CENT = Decimal("0.01")
_MAX_MONEY = Decimal("9999999999999999.99")


def _to_decimal(value: Any) -> Decimal:
    return Decimal("0") if value is None else Decimal(str(value))


def _compute_status(paid: Decimal, receivable: Decimal) -> str:
    if paid + _MONEY_EPSILON >= receivable:
        return RECEIVABLE_STATUS_PAID
    return RECEIVABLE_STATUS_PARTIAL if paid > 0 else RECEIVABLE_STATUS_UNPAID


def _existing_allocations(db: Any, sales_order_id: int) -> list[ReceivableAllocation]:
    return cast(
        "list[ReceivableAllocation]",
        apply_tenant_filter(db.query(ReceivableAllocation), ReceivableAllocation)
        .filter(
            ReceivableAllocation.sales_order_id == int(sales_order_id),
            ReceivableAllocation.status != RECEIVABLE_STATUS_REFUNDED,
        )
        .all(),
    )


def _sum_allocated(allocations: list[ReceivableAllocation]) -> Decimal:
    return sum((_to_decimal(a.allocated_amount) for a in allocations), Decimal("0"))


def _locked_order(db: Any, sales_order_id: int) -> Any:
    """Serialize amount checks and refunds on SQLite AND PostgreSQL.

    SELECT FOR UPDATE is ignored by SQLite. A tenant-filtered no-op UPDATE
    acquires its write lock before reading balances, and a row lock on PG.
    The caller retains the lock until its transaction ends.
    """
    db.flush()  # Preserve caller-owned invoice changes before populate_existing refreshes.
    query = apply_tenant_filter(db.query(SalesOrder), SalesOrder).filter(
        SalesOrder.id == int(sales_order_id)
    )
    if (
        query.update({SalesOrder.paid_amount: SalesOrder.paid_amount}, synchronize_session=False)
        != 1
    ):
        return None
    return query.populate_existing().first()


def _fingerprint(
    amount: Decimal,
    partner_id: int | None,
    partner_name: str | None,
    reference: str | None,
    journal_date: date | None,
) -> str:
    # None is retained for the implicit date, so retries across midnight match.
    payload = [
        format(amount, ".2f"),
        partner_id,
        partner_name,
        reference,
        journal_date.isoformat() if journal_date else None,
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def payment(
    *,
    sales_order_id: int,
    amount: Any,
    partner_id: int | None = None,
    partner_name: str | None = None,
    reference: str | None = None,
    journal_date: date | None = None,
    idempotency_key: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """Post one payment; repeated keys must carry exactly the same payload.

    Keys are scoped to the authorized order and survive refunds. No-key calls
    intentionally create distinct payments, even when their amounts are equal.
    The external ``db`` ownership/commit contract is unchanged.
    """
    try:
        amount_dec = _to_decimal(amount)
        if (
            not amount_dec.is_finite()
            or not 0 < amount_dec <= _MAX_MONEY
            or amount_dec != amount_dec.quantize(_CENT)
        ):
            raise ValueError("invalid amount")
        amount_dec = amount_dec.quantize(_CENT)
    except (ValueError, TypeError, InvalidOperation):
        return {"success": False, "message": "收款金额必须大于 0，且为有效的两位小数金额"}
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 128
    ):
        return {"success": False, "message": "idempotency_key 必须为 1–128 字符的非空字符串"}
    key = idempotency_key.strip() if idempotency_key is not None else None
    fingerprint = _fingerprint(amount_dec, partner_id, partner_name, reference, journal_date)
    with get_db() if db is None else nullcontext(db) as ctx:
        order = _locked_order(ctx, sales_order_id)
        if order is None:
            return {"success": False, "message": f"销售订单不存在: sales_order_id={sales_order_id}"}
        if key is not None:
            prior = (
                apply_tenant_filter(ctx.query(ReceivableAllocation), ReceivableAllocation)
                .filter(
                    ReceivableAllocation.sales_order_id == int(sales_order_id),
                    ReceivableAllocation.request_key == key,
                )
                .populate_existing()
                .first()
            )
            if prior is not None:
                if prior.request_fingerprint != fingerprint:
                    return {
                        "success": False,
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "同一收款幂等键不能用于不同请求",
                    }
                return {
                    "success": True,
                    "idempotent": True,
                    "message": "收款请求已处理，返回原分配",
                    "data": prior.to_dict(),
                }

        receivable = _to_decimal(order.total_amount)
        current_allocated = _sum_allocated(_existing_allocations(ctx, sales_order_id))
        new_total = current_allocated + amount_dec
        if new_total > receivable + _MONEY_EPSILON:
            return {
                "success": False,
                "message": (
                    f"累计收款超应收被拒: 应收 ¥{receivable}，"
                    f"已收 ¥{current_allocated}，本次 ¥{amount_dec}"
                ),
            }
        entry_result = create_journal_entry(
            {
                "journal_date": journal_date or date.today(),
                "description": f"收款-订单{sales_order_id}"
                + (f"-{reference}" if reference else ""),
                "reference_type": "payment",
                "reference_id": int(sales_order_id),
                "lines": [
                    {
                        "account_code": CASH_ACCOUNT_CODE,
                        "account_name": "库存现金",
                        "debit": amount_dec,
                        "credit": 0,
                    },
                    {
                        "account_code": RECEIVABLE_ACCOUNT_CODE,
                        "account_name": "应收账款",
                        "debit": 0,
                        "credit": amount_dec,
                        "partner_id": partner_id,
                        "partner_name": partner_name,
                    },
                ],
            },
            db=ctx,
        )
        if not entry_result.get("success"):
            return entry_result
        entry_data = entry_result.get("data") or {}
        status = _compute_status(new_total, receivable)
        alloc = ReceivableAllocation(
            sales_order_id=int(sales_order_id),
            journal_entry_id=entry_data.get("id"),
            line_id=_find_line_id(entry_data, RECEIVABLE_ACCOUNT_CODE),
            amount=amount_dec,
            allocated_amount=amount_dec,
            status=status,
            reference_type="payment",
            reference_id=int(sales_order_id),
            request_key=key,
            request_fingerprint=fingerprint if key is not None else None,
            allocated_at=datetime.now(),
        )
        ctx.add(alloc)
        order.paid_amount, order.payment_state = new_total, status
        ctx.flush()
        ctx.refresh(alloc)
        return {
            "success": True,
            "message": f"收款成功 ¥{amount_dec}，累计 ¥{new_total}，状态 {status}",
            "data": alloc.to_dict(),
        }


def refund(
    *, allocation_id: int, reference: str | None = None, journal_date: date | None = None
) -> dict[str, Any]:
    """Reverse a receipt, serialized against other payments/refunds of its order."""
    with get_db() as db:
        query = apply_tenant_filter(db.query(ReceivableAllocation), ReceivableAllocation).filter(
            ReceivableAllocation.id == int(allocation_id)
        )
        alloc = query.first()
        if alloc is None:
            return {"success": False, "message": f"收款分配不存在: allocation_id={allocation_id}"}
        if alloc.sales_order_id is not None:
            if _locked_order(db, alloc.sales_order_id) is None:
                return {"success": False, "message": "销售订单不存在或不可访问"}
        else:
            query.update(
                {ReceivableAllocation.amount: ReceivableAllocation.amount},
                synchronize_session=False,
            )
        alloc = query.populate_existing().one()
        if alloc.status == RECEIVABLE_STATUS_REFUNDED:
            return {
                "success": True,
                "idempotent": True,
                "message": "该收款分配已退款/冲销，幂等返回",
                "data": alloc.to_dict(),
            }
        amount_dec = _to_decimal(alloc.allocated_amount)
        entry_result = create_journal_entry(
            {
                "journal_date": journal_date or date.today(),
                "description": f"收款退款/冲销-分配{allocation_id}"
                + (f"-{reference}" if reference else ""),
                "reference_type": "refund",
                "reference_id": int(allocation_id),
                "lines": [
                    {
                        "account_code": RECEIVABLE_ACCOUNT_CODE,
                        "account_name": "应收账款",
                        "debit": amount_dec,
                        "credit": 0,
                    },
                    {
                        "account_code": CASH_ACCOUNT_CODE,
                        "account_name": "库存现金",
                        "debit": 0,
                        "credit": amount_dec,
                    },
                ],
            },
            db=db,
        )
        if not entry_result.get("success"):
            return entry_result
        alloc.status, alloc.allocated_at = RECEIVABLE_STATUS_REFUNDED, datetime.now()
        entry_data = entry_result.get("data") or {}
        reversal = ReceivableAllocation(
            sales_order_id=alloc.sales_order_id,
            journal_entry_id=entry_data.get("id"),
            line_id=_find_line_id(entry_data, RECEIVABLE_ACCOUNT_CODE),
            amount=amount_dec,
            allocated_amount=amount_dec,
            status=RECEIVABLE_STATUS_REFUNDED,
            reference_type="reversal",
            reference_id=int(allocation_id),
            reversed_of_id=int(allocation_id),
            allocated_at=datetime.now(),
        )
        db.add(reversal)
        if alloc.sales_order_id is not None:
            _update_order_after_refund(db, alloc)
        db.flush()
        db.refresh(reversal)
        return {
            "success": True,
            "message": f"收款已退款/冲销 ¥{amount_dec}",
            "data": reversal.to_dict(),
        }


def _update_order_after_refund(db: Any, alloc: ReceivableAllocation) -> None:
    if alloc.sales_order_id is None:
        return
    order = (
        apply_tenant_filter(db.query(SalesOrder), SalesOrder)
        .filter(SalesOrder.id == alloc.sales_order_id)
        .first()
    )
    if order is not None:
        remaining = _sum_allocated(
            [a for a in _existing_allocations(db, alloc.sales_order_id) if a.id != alloc.id]
        )
        order.paid_amount = remaining
        order.payment_state = _compute_status(remaining, _to_decimal(order.total_amount))


def _find_line_id(entry_data: dict[str, Any], account_code: str) -> int | None:
    for line in entry_data.get("lines") or []:
        if line.get("account_code") == account_code:
            return cast("int | None", line.get("id"))
    return None


__all__ = ["payment", "refund"]
