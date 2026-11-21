"""Read sales postconditions from the original tenant/Mod SQL authorities.

This adapter never calls a sales command. Before dispatch the host records a
read-only observation in the frozen verification contract. Afterwards movement,
allocation and journal identities must match that observation and the request;
an executor's success flag or an unrelated pre-existing row proves nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.application.agent_orchestrator.verification_readback import _report
from app.db.models import InventoryTransaction, JournalEntry, ReceivableAllocation, SalesOrder
from app.utils.operational_errors import RECOVERABLE_ERRORS

SALES_ACTIONS = frozenset({"confirm", "cancel", "deliver", "invoice", "payment", "credit_note"})


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid quantity")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("nonfinite quantity")
    return number


@contextmanager
def sales_read_scope(context: dict[str, Any], action: str):
    from app.db import SessionLocal
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    actor = _bound_actor(context)
    tenant = str(context.get("tenant_id") or "")
    permissions = set(get_auth_service().get_user_permissions(actor))
    required = {"tool.sales.query"}
    if action in {"invoice", "credit_note", "payment"}:
        required.add("tool.finance.ledger_query")
    if not tenant.isdigit() or int(tenant) <= 0 or not required <= permissions:
        raise PermissionError("sales_read_permission_unavailable")
    token = set_request_active_mod_id("")
    try:
        with (
            owned_tenant_scope(int(tenant)),
            agent_mod_execution_scope(context.get("_mod_authorization")),
            SessionLocal() as db,
        ):
            yield db, int(tenant)
    finally:
        reset_request_active_mod_id(token)


def _order(db, tenant: int, order_id: Any):
    return db.scalar(
        select(SalesOrder).where(SalesOrder.tenant_id == tenant, SalesOrder.id == int(order_id))
    )


def capture_sales_baseline(step, context: dict[str, Any]) -> dict[str, Any]:
    """Called only by the host before dispatch; unavailable evidence stays unknown."""
    try:
        with sales_read_scope(context, step.action) as (db, tenant):
            order = _order(db, tenant, step.params["order_id"])
            if order is None:
                return {"status": "unavailable", "code": "sales_order_not_visible"}
            result = {
                "status": "observed",
                "source": "sales_sql",
                "tenant_id": str(tenant),
                "order_id": order.id,
                "state": order.state,
                "total_amount": str(order.total_amount),
                "paid_amount": str(order.paid_amount or 0),
            }
            for name, model, column in (
                ("movement", InventoryTransaction, InventoryTransaction.sales_order_id),
                ("allocation", ReceivableAllocation, ReceivableAllocation.sales_order_id),
                ("journal", JournalEntry, JournalEntry.reference_id),
            ):
                result[name + "_cursor"] = (
                    db.scalar(
                        select(func.max(model.id)).where(
                            model.tenant_id == tenant, column == order.id
                        )
                    )
                    or 0
                )
            if step.action == "deliver":
                item = next(
                    (
                        row
                        for row in order.items
                        if row.tenant_id == tenant and row.id == int(step.params["item_id"])
                    ),
                    None,
                )
                if item is None:
                    return {"status": "unavailable", "code": "sales_item_not_visible"}
                result.update(item_id=item.id, delivered_quantity=str(item.delivered_quantity or 0))
            return result
    except (KeyError, ValueError, TypeError, PermissionError) + RECOVERABLE_ERRORS:
        return {"status": "unavailable", "code": "sales_baseline_unavailable"}


def _matching_claim(data: dict, actual: dict) -> bool:
    """Check every claimed business field that has an authoritative counterpart."""
    for key, expected in actual.items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(expected, Decimal):
            if _decimal(value) != expected:
                return False
        elif value != expected:
            return False
    return True


def _journal(db, tenant, entry_id, order_id, kind, amount):
    row = db.scalar(
        select(JournalEntry).where(JournalEntry.tenant_id == tenant, JournalEntry.id == entry_id)
    )
    if (
        row is None
        or row.reference_id != order_id
        or row.reference_type != kind
        or row.status != "posted"
        or row.reversed_at is not None
        or not row.lines
        or any(line.tenant_id != tenant for line in row.lines)
        or _decimal(row.debit_total) != amount
        or _decimal(row.credit_total) != amount
        or not row.is_balanced()
    ):
        return None
    expected = {
        "sale": {("1122", amount, Decimal(0)), ("6001", Decimal(0), amount)},
        "payment": {("1001", amount, Decimal(0)), ("1122", Decimal(0), amount)},
        "credit-note": {("6001", amount, Decimal(0)), ("1122", Decimal(0), amount)},
    }[kind]
    lines = {(line.account_code, _decimal(line.debit), _decimal(line.credit)) for line in row.lines}
    return row if len(row.lines) == 2 and lines == expected else None


def _delivery(db, tenant, order, step, data, before):
    params = step.params
    item = next(
        (
            row
            for row in order.items
            if row.tenant_id == tenant and row.id == int(params["item_id"])
        ),
        None,
    )
    if item is None or before.get("item_id") != item.id:
        return None
    quantity = _decimal(params["quantity"])
    rows = list(
        db.scalars(
            select(InventoryTransaction).where(
                InventoryTransaction.tenant_id == tenant,
                InventoryTransaction.sales_order_id == order.id,
                InventoryTransaction.sales_order_item_id == item.id,
                InventoryTransaction.transaction_type == "out",
            )
        )
    )
    key = params.get("idempotency_key")
    if key:
        marker = f"idempotency:deliver:{key}"
        rows = [
            row
            for row in rows
            if row.remark == marker or str(row.remark or "").startswith(marker + " | ")
        ]
    else:
        rows = [row for row in rows if row.id > before["movement_cursor"]]
    if len(rows) != 1:
        return None
    movement = rows[0]
    if (
        quantity <= 0
        or movement.warehouse_id != int(params["warehouse_id"])
        or movement.product_id != item.product_id
        or _decimal(movement.quantity) != -quantity
        or movement.reference_type != "sale_delivery"
        or movement.reference_id != order.id
        or _decimal(movement.delivered_quantity) != quantity
        or movement.before_quantity is None
        or movement.after_quantity is None
        or _decimal(movement.before_quantity) - _decimal(movement.after_quantity) != quantity
        or (
            not key
            and _decimal(item.delivered_quantity)
            != _decimal(before["delivered_quantity"]) + quantity
        )
        or _decimal(item.delivered_quantity) < quantity
        or data.get("order_id") != order.id
        or data.get("item_id") != item.id
        or not _matching_claim(
            data,
            {
                "order_id": order.id,
                "item_id": item.id,
                "product_id": item.product_id,
                "delivered_quantity": _decimal(item.delivered_quantity),
                "reserved_quantity": _decimal(item.reserved_quantity),
            },
        )
    ):
        return None
    return {"movement_id": movement.id, "item_id": item.id, "quantity": str(quantity)}


def _accounting(db, tenant, order, step, data, before):
    action = step.action
    row_id = data.get("id")
    if type(row_id) is not int or row_id <= 0:
        return None
    amount = _decimal(order.total_amount)
    if action == "payment":
        amount = _decimal(step.params["amount"])
        allocation = db.scalar(
            select(ReceivableAllocation).where(
                ReceivableAllocation.tenant_id == tenant,
                ReceivableAllocation.id == row_id,
                ReceivableAllocation.sales_order_id == order.id,
            )
        )
        key = step.params.get("idempotency_key")
        if (
            allocation is None
            or allocation.status == "refunded"
            or allocation.reference_type != "payment"
            or allocation.reference_id != order.id
            or _decimal(allocation.amount) != amount
            or _decimal(allocation.allocated_amount) != amount
            or (key and allocation.request_key != key)
            or (not key and allocation.id <= before["allocation_cursor"])
            or not _matching_claim(
                data,
                {
                    "id": allocation.id,
                    "sales_order_id": order.id,
                    "journal_entry_id": allocation.journal_entry_id,
                    "line_id": allocation.line_id,
                    "status": allocation.status,
                    "reference_type": "payment",
                    "reference_id": order.id,
                    "amount": amount,
                    "allocated_amount": amount,
                },
            )
        ):
            return None
        paid = db.scalar(
            select(func.sum(ReceivableAllocation.allocated_amount)).where(
                ReceivableAllocation.tenant_id == tenant,
                ReceivableAllocation.sales_order_id == order.id,
                ReceivableAllocation.status != "refunded",
            )
        ) or Decimal(0)
        if _decimal(order.paid_amount) != _decimal(paid):
            return None
        entry = _journal(db, tenant, allocation.journal_entry_id, order.id, "payment", amount)
        from app.application.payment_service import _compute_status

        if order.payment_state != _compute_status(_decimal(paid), _decimal(order.total_amount)):
            return None
        if entry and not any(
            line.id == allocation.line_id and line.account_code == "1122" for line in entry.lines
        ):
            return None
        return (
            {"allocation_id": allocation.id, "journal_entry_id": entry.id, "amount": str(amount)}
            if entry
            else None
        )
    kind = "sale" if action == "invoice" else "credit-note"
    entry = _journal(db, tenant, row_id, order.id, kind, amount)
    if entry is None or not _matching_claim(
        data,
        {
            "id": entry.id,
            "reference_id": order.id,
            "reference_type": kind,
            "debit_total": amount,
            "credit_total": amount,
            "status": "posted",
        },
    ):
        return None
    if action == "invoice":
        if order.invoice_status != "invoiced" or entry.is_credit_note or entry.reversed_of_id:
            return None
    else:
        original = db.scalar(
            select(JournalEntry).where(
                JournalEntry.tenant_id == tenant,
                JournalEntry.id == entry.reversed_of_id,
                JournalEntry.reference_id == order.id,
                JournalEntry.reference_type == "sale",
            )
        )
        if (
            order.invoice_status != "credit_note"
            or entry.is_credit_note != 1
            or entry.id <= before["journal_cursor"]
            or original is None
            or original.reversed_at is None
            or _decimal(original.debit_total) != amount
            or _decimal(original.credit_total) != amount
            or not original.is_balanced()
            or any(line.tenant_id != tenant for line in original.lines)
        ):
            return None
    return {
        "journal_entry_id": entry.id,
        "reversed_of_id": entry.reversed_of_id,
        "amount": str(amount),
    }


def verify_sales_result(step, call, output: dict, context: dict) -> dict:
    before = (call.metadata.get("verification_contract") or {}).get("authority_baseline") or {}
    if before.get("status") != "observed":
        return _report("inconclusive", "sales_baseline_unavailable", "sales_sql")
    with sales_read_scope(context, step.action) as (db, tenant):
        order = _order(db, tenant, step.params["order_id"])
        if order is None:
            return _report("inconclusive", "sales_order_not_visible", "sales_sql")
        if before.get("tenant_id") != str(tenant) or before.get("order_id") != order.id:
            return _report("failed", "sales_scope_mismatch", "sales_sql")
        data = output.get("data")
        if not isinstance(data, dict):
            return _report("inconclusive", "sales_receipt_identity_missing", "sales_sql")
        evidence = None
        if step.action in {"confirm", "cancel"}:
            expected = "confirmed" if step.action == "confirm" else "cancel"
            if (
                order.state == expected
                and data.get("id") == order.id
                and _matching_claim(
                    data,
                    {
                        "id": order.id,
                        "state": expected,
                        "status": order.status,
                        "invoice_status": order.invoice_status,
                        "payment_state": order.payment_state,
                        "total_amount": _decimal(order.total_amount),
                        "paid_amount": _decimal(order.paid_amount or 0),
                    },
                )
            ):
                evidence = {"state": expected, "source_updated_at": str(order.updated_at)}
                if step.action == "cancel" and (
                    order.invoice_status != "not_invoiced"
                    or any(
                        _decimal(item.delivered_quantity or 0)
                        or _decimal(item.reserved_quantity or 0)
                        or _decimal(item.returned_quantity or 0)
                        for item in order.items
                        if item.tenant_id == tenant
                    )
                ):
                    evidence = None
        elif step.action == "deliver":
            evidence = _delivery(db, tenant, order, step, data, before)
        else:
            evidence = _accounting(db, tenant, order, step, data, before)
            if "entry_id" in output and output["entry_id"] != data.get("id"):
                evidence = None
        if evidence is None:
            return _report("inconclusive", "sales_authority_mismatch", "sales_sql")
        return _report(
            "verified",
            "result_verified",
            "sales_sql",
            tenant_id=str(tenant),
            order_id=order.id,
            action=step.action,
            postcondition_verified=True,
            attribution="not_inferred",
            **evidence,
        )
