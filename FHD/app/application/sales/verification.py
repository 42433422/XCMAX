"""Read back the committed sales result under the current tenant."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from sqlalchemy.orm import Session


def verify_closed_loop(payload: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    """Read back the committed sale. This step does not create or change business rows."""
    from decimal import Decimal

    from app.application.invoicing_service import find_sale_invoice_entry
    from app.application.sales.idempotency import closed_loop_order_no, closed_loop_payment_key
    from app.application.sales.validation import validate_arithmetic, validate_structure
    from app.db.models import (
        InventoryTransaction,
        ReceivableAllocation,
        SalesOrder,
        SalesOrderItem,
    )
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import TenantScopeError, tenant_id_for_write

    invalid = validate_structure(payload) or validate_arithmetic(payload)
    if invalid:
        return {**invalid, "retryable": False}
    key = payload["idempotency_key"].strip()
    order = payload["order"]
    try:
        tenant_id = tenant_id_for_write()
    except TenantScopeError:
        return {
            "success": False,
            "error_code": "NO_TENANT_CONTEXT",
            "message": "缺少当前租户上下文，拒绝核对",
            "retryable": False,
        }
    ordered = [Decimal(str(item["quantity"])) for item in order["items"]]
    shipped = [
        Decimal(str(quantity))
        for quantity in payload["fulfillment"].get("line_quantities", ordered)
    ]
    expected_amount = Decimal(str(order.get("total_amount")))
    payment = payload["payment_allocation"]
    invoice_requested = bool((payload.get("invoice") or {}).get("requested"))
    with nullcontext(db) if db is not None else get_db() as db:
        saved = (
            db.query(SalesOrder)
            .filter(SalesOrder.order_no == closed_loop_order_no(key, tenant_id))
            .one_or_none()
        )
        if saved is None:
            return {"success": False, "message": "未找到已提交的销售订单", "retryable": False}
        rows = (
            db.query(SalesOrderItem)
            .filter(SalesOrderItem.order_id == saved.id)
            .order_by(SalesOrderItem.id)
            .all()
        )
        outs = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.sales_order_id == saved.id,
                InventoryTransaction.transaction_type == "out",
            )
            .all()
        )
        invoice = find_sale_invoice_entry(db, saved.id) if invoice_requested else None
        paid = Decimal(str(saved.paid_amount or 0))
        quantity_ok = [Decimal(str(row.quantity)) for row in rows] == ordered
        amount_ok = Decimal(str(saved.total_amount)) == expected_amount
        stock_ok = quantity_ok and sorted(
            (transaction.sales_order_item_id or 0, abs(Decimal(str(transaction.quantity))))
            for transaction in outs
        ) == list(zip((row.id for row in rows), shipped, strict=True))
        invoice_ok = not invoice_requested or (
            invoice is not None
            and invoice.is_balanced()
            and invoice.debit_total == expected_amount
            and saved.invoice_status == "invoiced"
        )
        if payment["requested"]:
            receipt = (
                db.query(ReceivableAllocation)
                .filter(
                    ReceivableAllocation.sales_order_id == saved.id,
                    ReceivableAllocation.request_key == closed_loop_payment_key(key),
                    ReceivableAllocation.reference_type == "payment",
                )
                .one_or_none()
            )
            expected_payment = Decimal(str(payment["amount"]))
            payment_ok = (
                receipt is not None
                and receipt.status != "refunded"
                and receipt.allocated_amount == expected_payment
                and paid >= expected_payment
            )
        else:
            payment_ok = saved.payment_state == "unpaid" and paid == 0
        if not (quantity_ok and amount_ok and stock_ok and invoice_ok and payment_ok):
            return {
                "success": False,
                "message": "订单、库存、履约或应收与已批准载荷不一致",
                "retryable": False,
                "order_id": saved.id,
            }
        return {
            "success": True,
            "message": "销售结果与已批准载荷一致",
            "order_id": saved.id,
            "order_no": saved.order_no,
            "quantity": str(sum(shipped)),
            "amount": str(saved.total_amount),
            "payment_state": saved.payment_state,
            "paid_amount": str(paid),
            "remaining_receivable": str(expected_amount - paid) if invoice_requested else None,
        }


def verify_agent_closed_loop(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Bind the original sales transaction receipt to current, read-only ledger evidence."""
    from decimal import Decimal

    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.agent_orchestrator.tool_permission import (
        _fingerprint,
        _reread_claim,
        idempotency_scope_key,
    )
    from app.application.agent_orchestrator.verification_readback import _report
    from app.application.agent_orchestrator.verification_transactions import (
        _journal,
        _matching_claim,
        _transaction_read_scope,
    )
    from app.application.sales.idempotency import (
        closed_loop_payment_key,
        composite_fingerprint,
        verify_fingerprint,
    )
    from app.application.sales.references import resolve_products, resolve_warehouse
    from app.application.sales.validation import coerce_entity_id
    from app.db.models import Customer, InventoryTransaction, ReceivableAllocation, SalesOrder

    source = "sales_closed_loop_sql"
    payload, data = step.params.get("payload"), output.get("data")
    if not isinstance(payload, dict) or not isinstance(data, dict):
        return _report("inconclusive", "sales_receipt_identity_missing", source)
    key = idempotency_scope_key(context, step.tool_id, step.action, step.params)
    receipt = _reread_claim(key, durable_read_only=True)
    if receipt is None or receipt.get("inflight") or not isinstance(receipt.get("output"), dict):
        return _report("inconclusive", "result_receipt_unavailable", source)
    if receipt.get("fingerprint") != _fingerprint(step.params, context) or canonical_hash(
        receipt["output"]
    ) != canonical_hash(output):
        return _report("failed", "result_receipt_mismatch", source)
    required = {"tool.sales.query"}
    if payload["invoice"]["requested"] or payload["payment_allocation"]["requested"]:
        required.add("tool.finance.ledger_query")
    with _transaction_read_scope(context, required, "sales") as (db, tenant):
        current = verify_closed_loop(payload, db=db)
        if current.get("success") is not True:
            return _report("failed", "sales_authority_mismatch", source)
        order = (
            db.query(SalesOrder)
            .filter(SalesOrder.id == current["order_id"], SalesOrder.tenant_id == tenant)
            .one()
        )
        customer = (
            db.query(Customer)
            .filter(Customer.id == order.customer_id, Customer.tenant_id == tenant)
            .one_or_none()
        )
        approved = payload["order"]
        if (
            customer is None
            or (
                approved.get("customer_id") is not None
                and coerce_entity_id(approved["customer_id"], "resolve_customer", "customer_id")
                != customer.id
            )
            or (
                approved.get("customer_id") is None
                and approved.get("customer_name") != customer.customer_name
            )
        ):
            return _report("failed", "sales_scope_mismatch", source)
        # Customer resolution can create a compatibility customer; readback
        # deliberately uses the saved customer instead of that mutating resolver.
        products = resolve_products(db, approved, tenant)
        warehouse = resolve_warehouse(db, payload["fulfillment"], tenant)
        fingerprint = composite_fingerprint(
            {"id": customer.id, "name": customer.customer_name},
            products,
            warehouse,
            approved,
            payload["fulfillment"],
            payload["invoice"],
            payload["payment_allocation"],
        )
        verify_fingerprint(db, order.id, fingerprint)
        items = sorted(order.items, key=lambda item: item.id)
        if (
            type(data.get("order_id")) is not int
            or data["order_id"] != order.id
            or data.get("order_no") != current["order_no"]
            or not isinstance(data.get("item_ids"), list)
            or any(type(item_id) is not int for item_id in data["item_ids"])
            or data.get("item_ids") != [item.id for item in items]
            or len(items) != len(products)
            or any(
                item.tenant_id != tenant
                or item.product_id != product["product_id"]
                or item.unit != product["unit"]
                or item.unit_price != product["unit_price"]
                for item, product in zip(items, products, strict=True)
            )
        ):
            return _report("failed", "sales_receipt_mismatch", source)
        movements = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.sales_order_id == order.id,
                InventoryTransaction.tenant_id == tenant,
                InventoryTransaction.transaction_type == "out",
            )
            .all()
        )
        item_products = {item.id: item.product_id for item in items}
        if any(
            row.warehouse_id != warehouse["id"]
            or row.product_id != item_products.get(row.sales_order_item_id)
            or row.quantity >= 0
            for row in movements
        ):
            return _report("failed", "sales_delivery_mismatch", source)
        invoice_id, payment_id = data.get("invoice_entry_id"), data.get("payment_allocation_id")
        if payload["invoice"]["requested"]:
            if (
                type(invoice_id) is not int
                or _journal(
                    db, tenant, invoice_id, order.id, "sale", Decimal(str(approved["total_amount"]))
                )
                is None
            ):
                return _report("failed", "sales_invoice_mismatch", source)
        elif invoice_id is not None:
            return _report("failed", "sales_invoice_mismatch", source)
        if payload["payment_allocation"]["requested"]:
            allocation = (
                db.query(ReceivableAllocation)
                .filter(
                    ReceivableAllocation.id == payment_id,
                    ReceivableAllocation.tenant_id == tenant,
                    ReceivableAllocation.sales_order_id == order.id,
                    ReceivableAllocation.reference_type == "payment",
                    ReceivableAllocation.request_key
                    == closed_loop_payment_key(payload["idempotency_key"]),
                )
                .one_or_none()
            )
            if (
                allocation is None
                or type(payment_id) is not int
                or _journal(
                    db,
                    tenant,
                    allocation.journal_entry_id,
                    order.id,
                    "payment",
                    Decimal(str(payload["payment_allocation"]["amount"])),
                )
                is None
            ):
                return _report("failed", "sales_payment_mismatch", source)
        elif payment_id is not None:
            return _report("failed", "sales_payment_mismatch", source)
        expected = {
            "state": order.state,
            "fulfillment": order.fulfillment_state(),
            "invoice_status": order.invoice_status,
            "payment_state": order.payment_state,
            "total_amount": Decimal(str(order.total_amount)),
            "paid_amount": Decimal(str(order.paid_amount or 0)),
        }
        postconditions = data.get("postconditions")
        if (
            not isinstance(postconditions, dict)
            or set(postconditions) != set(expected)
            or not _matching_claim(postconditions, expected)
        ):
            return _report("failed", "sales_postconditions_changed", source)
        return _report(
            "verified",
            "result_verified",
            source,
            tenant_id=str(tenant),
            order_id=order.id,
            invoice_entry_id=invoice_id,
            payment_allocation_id=payment_id,
            inventory_movement_ids=sorted(row.id for row in movements),
            payload_sha256=canonical_hash(payload),
            transaction_fingerprint=fingerprint,
            receipt_sha256=canonical_hash(receipt["output"]),
            scope="current_sales_closed_loop_state",
            attribution="not_inferred",
        )
