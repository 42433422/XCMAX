"""Read original procurement documents, approved limits, stock and payable facts.

Reuse the host's SQLAlchemy tenant/Mod scope and original AgentRun contract.
No supplier endpoint or purchase command is called during verification.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import func, select

from app.application.agent_orchestrator.verification_readback import _report
from app.application.agent_orchestrator.verification_sales import _decimal
from app.db.models import (
    InventoryTransaction,
    JournalEntry,
    PurchaseInbound,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.domain.shared_services.purchase_service import purchase_execution_number
from app.utils.operational_errors import RECOVERABLE_ERRORS

PURCHASE_ACTIONS = frozenset(
    {"create_order", "update_order", "approve_order", "cancel_order", "create_inbound"}
)


@contextmanager
def purchase_read_scope(context, action):
    from app.db import SessionLocal
    from app.domain.shared_services.auth_service import get_auth_service
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    actor, tenant = _bound_actor(context), str(context.get("tenant_id") or "")
    required = {"tool.purchase.query_orders", f"tool.purchase.{action}"}
    if action == "create_inbound":
        required |= {"tool.purchase.query_inbounds", "tool.finance.ledger_query"}
    if (
        not tenant.isdigit()
        or int(tenant) <= 0
        or not required <= set(get_auth_service().get_user_permissions(actor))
    ):
        raise PermissionError("purchase_read_permission_unavailable")
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


def _order(db, tenant, identity):
    return db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant, PurchaseOrder.id == int(identity)
        )
    )


def _snapshot(order):
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
                order = _order(db, tenant, step.params["order_id"])
                if order is None or any(row.tenant_id != tenant for row in order.items):
                    return {"status": "unavailable", "reason": "original_order_not_visible"}
                baseline["original_order"] = _snapshot(order)
            return baseline
    except (ValueError, KeyError, TypeError, PermissionError) + RECOVERABLE_ERRORS:
        return {"status": "unavailable", "reason": "purchase_baseline_unavailable"}


def _items(rows, *, inbound=False):
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


def _amount(rows):
    return sum(
        (_decimal(row["quantity"]) * _decimal(row.get("unit_price", 0)) for row in rows), Decimal(0)
    ).quantize(Decimal("0.01"))


def _matching_claim(data, row):
    for key in (
        "id",
        "supplier_id",
        "warehouse_id",
        "status",
        "order_id",
        "order_no",
        "inbound_no",
    ):
        if key in data and data[key] != getattr(row, key, None):
            return False
    return "total_amount" not in data or _decimal(data["total_amount"]) == _decimal(
        row.total_amount
    )


def _inbound(db, tenant, step, data, before):
    row = db.scalar(
        select(PurchaseInbound).where(
            PurchaseInbound.tenant_id == tenant, PurchaseInbound.id == int(data.get("id") or 0)
        )
    )
    original = before.get("original_order") or {}
    order = _order(db, tenant, original.get("order_id", 0))
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
        or not _matching_claim(data, row)
        or _items(row.items, inbound=True) != _items(step.params.get("items") or [], inbound=True)
        or _decimal(row.total_amount) != _amount(step.params["items"])
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


def verify_purchase_result(step, call, output: dict, context: dict) -> dict:
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
            evidence = _inbound(db, tenant, step, data, before)
        else:
            order = _order(db, tenant, data["id"])
            if (
                order is not None
                and _matching_claim(data, order)
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
                        and _items(order.items) == _items(step.params.get("items") or [])
                        and _decimal(order.total_amount) == _amount(step.params["items"])
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
                            and _items(order.items) == _items(old["items"])
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
                                and _items(order.items) == _items(step.params["items"])
                                and _decimal(order.total_amount) == _amount(step.params["items"])
                            )
                        else:
                            valid = (
                                valid
                                and _items(order.items) == _items(old["items"])
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
