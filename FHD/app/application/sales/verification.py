"""Read back the committed sales result under the current tenant."""

from __future__ import annotations

from typing import Any


def verify_closed_loop(payload: dict[str, Any]) -> dict[str, Any]:
    """Read back the committed sale. This step does not create or change business rows."""
    from decimal import Decimal

    from app.application.sales.idempotency import closed_loop_order_no
    from app.db.models import InventoryTransaction, JournalEntry, SalesOrder, SalesOrderItem
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import TenantScopeError, tenant_id_for_write

    key = str(payload.get("idempotency_key") or "").strip()
    order = payload.get("order") if isinstance(payload.get("order"), dict) else None
    items = order.get("items") if isinstance(order, dict) else None
    item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
    if not key or order is None or item is None:
        return {"success": False, "message": "缺少已批准的销售载荷", "retryable": False}
    try:
        tenant_id = tenant_id_for_write()
    except TenantScopeError:
        return {
            "success": False,
            "error_code": "NO_TENANT_CONTEXT",
            "message": "缺少当前租户上下文，拒绝核对",
            "retryable": False,
        }
    expected_qty = Decimal(str(item.get("quantity")))
    expected_amount = Decimal(str(order.get("total_amount")))
    payment_requested = bool((payload.get("payment_allocation") or {}).get("requested"))
    invoice_requested = bool((payload.get("invoice") or {}).get("requested"))
    with get_db() as db:
        saved = (
            db.query(SalesOrder)
            .filter(SalesOrder.order_no == closed_loop_order_no(key, tenant_id))
            .one_or_none()
        )
        if saved is None:
            return {"success": False, "message": "未找到已提交的销售订单", "retryable": False}
        row = db.query(SalesOrderItem).filter(SalesOrderItem.order_id == saved.id).one_or_none()
        outs = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.sales_order_id == saved.id,
                InventoryTransaction.transaction_type == "out",
            )
            .all()
        )
        entries = (
            db.query(JournalEntry).filter(JournalEntry.reference_id == saved.id).count()
            if invoice_requested
            else 0
        )
        paid = Decimal(str(saved.paid_amount or 0))
        quantity_ok = row is not None and Decimal(str(row.quantity)) == expected_qty
        amount_ok = Decimal(str(saved.total_amount)) == expected_amount
        stock_ok = len(outs) == 1 and abs(Decimal(str(outs[0].quantity))) == expected_qty
        invoice_ok = (not invoice_requested) or entries >= 1
        payment_ok = payment_requested or (
            str(saved.payment_state or "") == "unpaid" and paid == Decimal("0")
        )
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
            "quantity": str(row.quantity),
            "amount": str(saved.total_amount),
            "payment_state": saved.payment_state,
            "paid_amount": str(paid),
        }
