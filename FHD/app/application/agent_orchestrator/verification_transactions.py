"""Verify original sales and purchase postconditions in the tenant/Mod ledger.

The host freezes read-only baselines before dispatch; afterwards the same order,
stock movement and receivable/payable journal must match that original request.
Sales and purchasing retain distinct permissions and receipt requirements. This
consumer neither calls transaction commands nor infers supplier-side completion.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.application.agent_orchestrator.run_models import AgentStep, ToolCall
from app.application.agent_orchestrator.verification_readback import _report
from app.db.models import (
    Customer,
    FinancialTransaction,
    InventoryTransaction,
    JournalEntry,
    PurchaseInbound,
    PurchaseOrder,
    PurchaseOrderItem,
    ReceivableAllocation,
    SalesOrder,
    Supplier,
)
from app.domain.shared_services.purchase_service import purchase_execution_number
from app.utils.operational_errors import RECOVERABLE_ERRORS

SALES_ACTIONS = frozenset({"confirm", "cancel", "deliver", "invoice", "payment", "credit_note"})
FINANCE_ACTIONS = frozenset({"create_transaction", "update_transaction", "delete_transaction"})
_FINANCE_UPDATABLE_FIELDS = frozenset(
    {
        "amount",
        "currency",
        "description",
        "status",
        "due_date",
        "transaction_date",
        "counterparty_name",
        "counterparty_id",
        "reference_type",
        "reference_id",
    }
)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdecimal():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid quantity")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("nonfinite quantity")
    return number


@contextmanager
def _transaction_read_scope(context: dict[str, Any], required: set[str], source: str):
    """Read the original ledger under the action's unchanged permission set."""
    from app.db import SessionLocal
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    actor = _bound_actor(context)
    tenant = str(context.get("tenant_id") or "")
    if (
        not tenant.isdigit()
        or int(tenant) <= 0
        or not required <= set(get_auth_service().get_user_permissions(actor))
    ):
        raise PermissionError(f"{source}_read_permission_unavailable")
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


def sales_read_scope(context: dict[str, Any], action: str):
    required = {"tool.sales.query"}
    if action in {"invoice", "credit_note", "payment"}:
        required.add("tool.finance.ledger_query")
    return _transaction_read_scope(context, required, "sales")


def _order(db, tenant: int, order_id: Any, model):
    return db.scalar(select(model).where(model.tenant_id == tenant, model.id == int(order_id)))


def verify_finance_creation(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read back the exact approved transaction from the original tenant."""
    from app.application.finance_app_service import _parse_dt, _valid_finance_amount

    source = "finance_sql"
    data = output.get("data")
    if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0:
        return _report("inconclusive", "result_finance_identity_missing", source)
    expected = {"currency": "CNY", **step.params}
    amount = _valid_finance_amount(expected.pop("amount", None))
    for field in ("transaction_date", "due_date"):
        if field in expected:
            parsed = _parse_dt(expected[field])
            if parsed is None:
                return _report("failed", "result_finance_effect_mismatch", source)
            expected[field] = parsed.replace(tzinfo=None).isoformat()
    reference = str(expected.get("reference_id") or "")
    if reference.isdecimal():
        expected["reference_id"] = int(reference)

    with _transaction_read_scope(context, {"tool.finance.ledger_query"}, source) as (db, tenant):
        row = _order(db, tenant, data["id"], FinancialTransaction)
        if row is None:
            return _report("inconclusive", "result_finance_record_unavailable", source)
        started = datetime.fromisoformat(call.started_at).astimezone(UTC).replace(tzinfo=None)
        historical = row.created_at < started
        if historical and not (expected.get("reference_type") and reference):
            return _report("failed", "result_finance_effect_mismatch", source)
        if not historical:
            expected.setdefault("status", "pending")
        snapshot = row.to_dict()
        if (
            row.amount != amount
            or data != snapshot
            or any(snapshot.get(key) != value for key, value in expected.items())
        ):
            return _report("failed", "result_finance_effect_mismatch", source)
        return _report(
            "verified", "result_verified", source, transaction_id=row.id, historical=historical
        )


def verify_finance_update(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Read back the exact updated transaction from the original tenant."""
    from app.application.finance_app_service import _parse_dt, _valid_finance_amount

    source = "finance_sql"
    txn_id = _positive_int(step.params.get("transaction_id"))
    data = output.get("data")
    if (
        txn_id is None
        or not isinstance(data, dict)
        or type(data.get("id")) is not int
        or data["id"] <= 0
    ):
        return _report("inconclusive", "result_finance_identity_missing", source)
    if data["id"] != txn_id:
        return _report("failed", "result_finance_effect_mismatch", source)

    expected = {
        key: value
        for key, value in step.params.items()
        if key in _FINANCE_UPDATABLE_FIELDS and value is not None
    }
    amount = _valid_finance_amount(expected.pop("amount")) if "amount" in expected else None
    for field in ("transaction_date", "due_date"):
        if field in expected:
            parsed = _parse_dt(expected[field])
            if parsed is None:
                return _report("failed", "result_finance_effect_mismatch", source)
            expected[field] = parsed.replace(tzinfo=None).isoformat()
    if "reference_id" in expected and str(expected["reference_id"]).isdecimal():
        expected["reference_id"] = int(str(expected["reference_id"]))

    with _transaction_read_scope(context, {"tool.finance.ledger_query"}, source) as (db, tenant):
        row = _order(db, tenant, txn_id, FinancialTransaction)
        if row is None:
            return _report("inconclusive", "result_finance_record_unavailable", source)
        started = datetime.fromisoformat(call.started_at).astimezone(UTC).replace(tzinfo=None)
        if row.updated_at is None or row.updated_at < started:
            return _report("failed", "result_finance_effect_mismatch", source)
        snapshot = row.to_dict()
        if (
            (amount is not None and row.amount != amount)
            or data != snapshot
            or any(snapshot.get(key) != value for key, value in expected.items())
        ):
            return _report("failed", "result_finance_effect_mismatch", source)
        return _report(
            "verified", "result_verified", source, transaction_id=row.id, action="update_transaction"
        )


def verify_finance_deletion(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Confirm the deleted transaction no longer exists in the original tenant."""
    source = "finance_sql"
    txn_id = _positive_int(step.params.get("transaction_id"))
    if txn_id is None:
        return _report("inconclusive", "result_finance_identity_missing", source)
    if output.get("success") is not True:
        return _report("failed", "result_finance_effect_mismatch", source)

    with _transaction_read_scope(context, {"tool.finance.ledger_query"}, source) as (db, tenant):
        row = _order(db, tenant, txn_id, FinancialTransaction)
        if row is not None:
            return _report("failed", "result_finance_effect_mismatch", source)
        return _report("verified", "result_verified", source, transaction_id=txn_id, deleted=True)


def verify_finance_result(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch finance write verification across create, update, and delete."""
    if step.action == "create_transaction":
        return verify_finance_creation(step, call, output, context)
    if step.action == "update_transaction":
        return verify_finance_update(step, call, output, context)
    if step.action == "delete_transaction":
        return verify_finance_deletion(step, call, output, context)
    return _report("inconclusive", "result_verifier_unavailable", "finance_sql")


def capture_sales_baseline(step, context: dict[str, Any]) -> dict[str, Any]:
    """Called only by the host before dispatch; unavailable evidence stays unknown."""
    try:
        with sales_read_scope(context, step.action) as (db, tenant):
            order = _order(db, tenant, step.params["order_id"], SalesOrder)
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


def _journal_lines_match(row, tenant, customer_id, kind, amount) -> bool:
    expected = {
        "sale": {("1122", amount, Decimal(0)), ("6001", Decimal(0), amount)},
        "payment": {("1001", amount, Decimal(0)), ("1122", Decimal(0), amount)},
        "credit-note": {("6001", amount, Decimal(0)), ("1122", Decimal(0), amount)},
        "refund": {("1122", amount, Decimal(0)), ("1001", Decimal(0), amount)},
    }[kind]
    return (
        len(row.lines) == 2
        and _decimal(row.debit_total) == amount
        and _decimal(row.credit_total) == amount
        and all(
            line.tenant_id == tenant
            and line.partner_id == (customer_id if line.account_code == "1122" else None)
            for line in row.lines
        )
        and {(line.account_code, _decimal(line.debit), _decimal(line.credit)) for line in row.lines}
        == expected
    )


def _invoice_journals_match(db, tenant, order, current) -> bool:
    """Reconcile active invoices with their original posted credit/reversal pairs."""
    posted = list(
        db.scalars(
            select(JournalEntry).where(
                JournalEntry.tenant_id == tenant,
                JournalEntry.reference_id == order.id,
                JournalEntry.reference_type.in_({"sale", "credit-note"}),
                JournalEntry.status == "posted",
            )
        )
    )
    invoices = {row.id: row for row in posted if row.reference_type == "sale"}
    credits = {row.reversed_of_id: row for row in posted if row.reference_type == "credit-note"}
    if len(invoices) + len(credits) != len(posted):
        return False
    invoice_ids = (
        select(JournalEntry.id)
        .where(
            JournalEntry.tenant_id == tenant,
            JournalEntry.reference_id == order.id,
            JournalEntry.reference_type == "sale",
        )
        .correlate(None)
    )
    reversals = db.scalars(
        select(JournalEntry).where(
            JournalEntry.tenant_id == tenant,
            JournalEntry.reference_type == "reversal",
            JournalEntry.status == "posted",
            or_(
                JournalEntry.reference_id.in_(invoice_ids),
                JournalEntry.reversed_of_id.in_(invoice_ids),
            ),
        )
    )
    for reversal in reversals:
        if (
            reversal.reversed_of_id not in invoices
            or reversal.reference_id != reversal.reversed_of_id
            or reversal.is_credit_note != 0
            or reversal.credit_note_of_id is not None
            or reversal.reversed_of_id in credits
        ):
            return False
        credits[reversal.reversed_of_id] = reversal
    active = set()
    for original in invoices.values():
        if original.is_credit_note or original.reversed_of_id is not None:
            return False
        if original.reversed_at is None:
            active.add(original.id)
            continue
        credit = credits.pop(original.id, None)
        if (
            credit is None
            or (credit.reference_type == "credit-note" and credit.is_credit_note != 1)
            or credit.reversed_at is not None
            or credit.credit_note_of_id not in {None, original.id}
            or not _journal_lines_match(
                original, tenant, order.customer_id, "sale", _decimal(original.debit_total)
            )
            or not _journal_lines_match(
                credit, tenant, order.customer_id, "credit-note", _decimal(original.debit_total)
            )
        ):
            return False
    expected = {current.id} if current.reference_type == "sale" else set()
    return not credits and active == expected


def _journal(db, tenant, entry_id, order_id, kind, amount, *, reference_id=None):
    order = _order(db, tenant, order_id, SalesOrder)
    row = db.scalar(
        select(JournalEntry).where(JournalEntry.tenant_id == tenant, JournalEntry.id == entry_id)
    )
    if (
        order is None
        or order.customer_id is None
        or db.scalar(
            select(Customer.id).where(
                Customer.tenant_id == tenant, Customer.id == order.customer_id
            )
        )
        is None
        or row is None
        or row.reference_id != (order_id if reference_id is None else reference_id)
        or row.reference_type != kind
        or row.status != "posted"
        or row.reversed_at is not None
        or (kind != "credit-note" and (row.reversed_of_id is not None or row.is_credit_note))
        or not _journal_lines_match(row, tenant, order.customer_id, kind, amount)
    ):
        return None
    if kind in {"sale", "credit-note"} and not _invoice_journals_match(db, tenant, order, row):
        return None
    return row


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
    from app.application.sales.payment_verification import verified_sales_payment_total

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
        if verified_sales_payment_total(db, tenant, order) is None:
            return None
        entry = _journal(db, tenant, allocation.journal_entry_id, order.id, "payment", amount)
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
    elif (
        order.invoice_status != "credit_note"
        or entry.is_credit_note != 1
        or entry.id <= before["journal_cursor"]
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
        order = _order(db, tenant, step.params["order_id"], SalesOrder)
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


PURCHASE_ACTIONS = frozenset(
    {"create_order", "update_order", "approve_order", "cancel_order", "create_inbound"}
)


def purchase_read_scope(context, action):
    required = {"tool.purchase.query_orders", f"tool.purchase.{action}"}
    if action == "create_inbound":
        required |= {"tool.purchase.query_inbounds", "tool.finance.ledger_query"}
    return _transaction_read_scope(context, required, "purchase")


def _purchase_snapshot(order):
    return {
        "order_id": order.id,
        "status": order.status,
        "supplier_id": order.supplier_id,
        "warehouse_id": order.warehouse_id,
        "total_amount": str(order.total_amount),
        "updated_at": str(order.updated_at),
        "items": [
            {
                "id": row.id,
                "product_id": row.product_id,
                "quantity": str(row.quantity),
                "unit_price": str(row.unit_price),
                "received_quantity": str(row.received_quantity or 0),
                "unit": row.unit,
            }
            for row in order.items
        ],
    }


def capture_purchase_baseline(run, step, context):
    try:
        with purchase_read_scope(context, step.action) as (db, tenant):
            baseline = {"status": "observed", "tenant_id": str(tenant)}
            for name, model in (
                ("order", PurchaseOrder),
                ("line", PurchaseOrderItem),
                ("inbound", PurchaseInbound),
                ("movement", InventoryTransaction),
                ("journal", JournalEntry),
            ):
                baseline[name + "_cursor"] = (
                    db.scalar(select(func.max(model.id)).where(model.tenant_id == tenant)) or 0
                )
            if step.action in {"create_order", "create_inbound"}:
                baseline["execution_number"] = purchase_execution_number(
                    step.action, run.run_id, step.step_id, str(tenant)
                )
            if step.action != "create_order":
                order = _order(db, tenant, step.params["order_id"], PurchaseOrder)
                if order is None or any(row.tenant_id != tenant for row in order.items):
                    return {"status": "unavailable", "reason": "original_order_not_visible"}
                baseline["original_order"] = _purchase_snapshot(order)
            return baseline
    except (ValueError, KeyError, TypeError, PermissionError) + RECOVERABLE_ERRORS:
        return {"status": "unavailable", "reason": "purchase_baseline_unavailable"}


def _purchase_items(rows, *, inbound=False):
    result = Counter()
    for raw in rows:
        row = (
            raw
            if isinstance(raw, dict)
            else {
                key: getattr(raw, key, None)
                for key in ("product_id", "quantity", "unit_price", "unit", "order_item_id")
            }
        )
        quantity, price = _decimal(row.get("quantity")), _decimal(row.get("unit_price", 0))
        if quantity <= 0 or price < 0:
            raise ValueError("invalid purchase amount")
        result[
            (
                int(row["product_id"]),
                quantity,
                price,
                str(row.get("unit") or "个"),
                row.get("order_item_id") if inbound else None,
            )
        ] += 1
    return result


def _purchase_amount(rows):
    return sum(
        (_decimal(row["quantity"]) * _decimal(row.get("unit_price", 0)) for row in rows), Decimal(0)
    ).quantize(Decimal("0.01"))


def _purchase_claim(data, row):
    return _matching_claim(
        data,
        {
            **{
                key: getattr(row, key, None)
                for key in (
                    "id",
                    "supplier_id",
                    "warehouse_id",
                    "status",
                    "order_id",
                    "order_no",
                    "inbound_no",
                )
            },
            "total_amount": _decimal(row.total_amount),
        },
    )


def _purchase_inbound(db, tenant, step, data, before):
    row = db.scalar(
        select(PurchaseInbound).where(
            PurchaseInbound.tenant_id == tenant, PurchaseInbound.id == int(data.get("id") or 0)
        )
    )
    original = before.get("original_order") or {}
    order = _order(db, tenant, original.get("order_id", 0), PurchaseOrder)
    if (
        row is None
        or order is None
        or row.id <= before["inbound_cursor"]
        or row.inbound_no != before["execution_number"]
        or row.status != "completed"
        or row.order_id != order.id
        or original.get("status") not in {"approved", "partial"}
        or any(item.tenant_id != tenant for item in row.items)
        or row.supplier_id != original.get("supplier_id")
        or row.warehouse_id != original.get("warehouse_id")
        or row.supplier_id != step.params.get("supplier_id")
        or row.warehouse_id != step.params.get("warehouse_id")
        or not _purchase_claim(data, row)
        or _purchase_items(row.items, inbound=True)
        != _purchase_items(step.params.get("items") or [], inbound=True)
        or _decimal(row.total_amount) != _purchase_amount(step.params["items"])
    ):
        return None
    original_lines = {item["id"]: item for item in original["items"]}
    increments = {}
    for item in row.items:
        allowed = original_lines.get(item.order_item_id)
        if (
            allowed is None
            or allowed["product_id"] != item.product_id
            or _decimal(allowed["unit_price"]) != _decimal(item.unit_price)
        ):
            return None
        increments[item.order_item_id] = increments.get(item.order_item_id, Decimal(0)) + _decimal(
            item.quantity
        )
    if set(original_lines) != {item.id for item in order.items}:
        return None
    for item in order.items:
        allowed = original_lines[item.id]
        if (
            item.tenant_id != tenant
            or _decimal(item.received_quantity or 0)
            != _decimal(allowed["received_quantity"]) + increments.get(item.id, Decimal(0))
            or _decimal(item.quantity) != _decimal(allowed["quantity"])
            or _decimal(item.received_quantity or 0) > _decimal(allowed["quantity"])
        ):
            return None
    movements = list(
        db.scalars(
            select(InventoryTransaction).where(
                InventoryTransaction.tenant_id == tenant,
                InventoryTransaction.reference_type == "purchase_inbound",
                InventoryTransaction.reference_id == row.id,
                InventoryTransaction.id > before["movement_cursor"],
            )
        )
    )
    expected = Counter(
        (item.product_id, _decimal(item.quantity), _decimal(item.unit_price or 0))
        for item in row.items
    )
    observed = Counter()
    for movement in movements:
        if (
            movement.transaction_type != "in"
            or movement.warehouse_id != row.warehouse_id
            or _decimal(movement.after_quantity) - _decimal(movement.before_quantity)
            != _decimal(movement.quantity)
        ):
            return None
        observed[
            (movement.product_id, _decimal(movement.quantity), _decimal(movement.unit_price or 0))
        ] += 1
    if not expected or observed != expected:
        return None
    journal = db.scalar(
        select(JournalEntry).where(
            JournalEntry.tenant_id == tenant,
            JournalEntry.id == int(data.get("journal_entry_id") or 0),
            JournalEntry.id > before["journal_cursor"],
            JournalEntry.reference_type == "purchase_inbound",
            JournalEntry.reference_id == row.id,
        )
    )
    if _decimal(row.total_amount) > 0 and (
        journal is None
        or journal.status != "posted"
        or journal.reversed_at is not None
        or journal.reversed_of_id is not None
        or _decimal(journal.debit_total) != _decimal(row.total_amount)
        or _decimal(journal.credit_total) != _decimal(row.total_amount)
    ):
        return None
    if journal is not None:
        if any(line.tenant_id != tenant for line in journal.lines):
            return None
        actual = Counter(
            (
                line.account_code,
                _decimal(line.debit or 0),
                _decimal(line.credit or 0),
                line.partner_id,
            )
            for line in journal.lines
        )
        if actual != Counter(
            {
                ("1401", _decimal(row.total_amount), Decimal(0), None): 1,
                ("2201", Decimal(0), _decimal(row.total_amount), row.supplier_id): 1,
            }
        ):
            return None
    return {
        "inbound_id": row.id,
        "order_id": order.id,
        "execution_number": row.inbound_no,
        "movement_ids": [item.id for item in movements],
        "journal_entry_id": journal.id if journal else None,
        "external_purchase_verified": False,
    }


def verify_purchase_result(
    step: AgentStep, call: ToolCall, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    before = (call.metadata.get("verification_contract") or {}).get("authority_baseline") or {}
    if before.get("status") != "observed":
        return _report("inconclusive", "purchase_baseline_unavailable", "purchase_sql")
    with purchase_read_scope(context, step.action) as (db, tenant):
        if before.get("tenant_id") != str(tenant):
            return _report("failed", "purchase_scope_mismatch", "purchase_sql")
        data = output.get("data")
        if not isinstance(data, dict) or type(data.get("id")) is not int:
            return _report("inconclusive", "purchase_receipt_identity_missing", "purchase_sql")
        evidence = None
        if step.action == "create_inbound":
            evidence = _purchase_inbound(db, tenant, step, data, before)
        else:
            order = _order(db, tenant, data["id"], PurchaseOrder)
            if (
                order is not None
                and _purchase_claim(data, order)
                and all(item.tenant_id == tenant for item in order.items)
            ):
                supplier = db.scalar(
                    select(Supplier).where(
                        Supplier.tenant_id == tenant, Supplier.id == order.supplier_id
                    )
                )
                valid = supplier is not None and supplier.status == "active"
                if step.action == "create_order":
                    valid = (
                        valid
                        and order.id > before["order_cursor"]
                        and order.status == "draft"
                        and order.order_no == before["execution_number"]
                        and order.supplier_id == step.params.get("supplier_id")
                        and order.warehouse_id == step.params.get("warehouse_id")
                        and all(item.id > before["line_cursor"] for item in order.items)
                        and bool(order.items)
                        and _purchase_items(order.items)
                        == _purchase_items(step.params.get("items") or [])
                        and _decimal(order.total_amount) == _purchase_amount(step.params["items"])
                    )
                else:
                    old = before.get("original_order") or {}
                    valid = valid and order.id == old.get("order_id") == step.params.get("order_id")
                    valid = valid and str(order.updated_at) != old.get("updated_at")
                    if step.action == "approve_order":
                        valid = (
                            valid
                            and old.get("status") == "draft"
                            and order.status == "approved"
                            and order.approve_date is not None
                            and _purchase_items(order.items) == _purchase_items(old["items"])
                            and order.supplier_id == old["supplier_id"]
                            and order.warehouse_id == old["warehouse_id"]
                            and _decimal(order.total_amount) == _decimal(old["total_amount"])
                        )
                    elif step.action == "cancel_order":
                        valid = (
                            valid
                            and old.get("status") not in {"completed", "cancelled"}
                            and order.status == "cancelled"
                        )
                    else:
                        valid = valid and order.status in {"draft", "rejected"}
                        if "items" in step.params:
                            valid = (
                                valid
                                and _purchase_items(order.items)
                                == _purchase_items(step.params["items"])
                                and _decimal(order.total_amount)
                                == _purchase_amount(step.params["items"])
                            )
                        else:
                            valid = (
                                valid
                                and _purchase_items(order.items) == _purchase_items(old["items"])
                                and _decimal(order.total_amount) == _decimal(old["total_amount"])
                            )
                        for key in ("remark", "supplier_id", "warehouse_id"):
                            if key in step.params:
                                valid = valid and getattr(order, key) == step.params[key]
                if valid:
                    evidence = {
                        "order_id": order.id,
                        "order_no": order.order_no,
                        "order_status": order.status,
                        "total_amount": str(order.total_amount),
                        "postcondition_verified": True,
                        "external_purchase_verified": False,
                    }
        if evidence is None:
            return _report("inconclusive", "purchase_authority_mismatch", "purchase_sql")
        return _report(
            "verified",
            "result_verified",
            "purchase_sql",
            tenant_id=str(tenant),
            action=step.action,
            **evidence,
        )
