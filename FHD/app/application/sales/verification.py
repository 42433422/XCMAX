"""Read back the committed sales result under the current tenant."""

from __future__ import annotations

from typing import Any


def verify_closed_loop(payload: dict[str, Any]) -> dict[str, Any]:
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
    with get_db() as db:
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
