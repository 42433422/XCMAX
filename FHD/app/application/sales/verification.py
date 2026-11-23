"""Read back the committed sales result under the current tenant."""

from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.application.sales.validation import finite_decimal


def _inventory_matches(db, tenant_id: int, order_id: int, rows, outs, shipped, key: str) -> bool:
    """Reconcile each original stock move through later moves to its physical ledger."""
    from app.db.models import InventoryLedger, InventoryTransaction, StorageLocation

    if len(rows) != len(outs):
        return False
    by_item = {movement.sales_order_item_id: movement for movement in outs}
    if len(by_item) != len(rows):
        return False
    ledgers: dict[int, InventoryTransaction] = {}
    original_movement_ids = {movement.id for movement in outs}
    for index, (item, quantity) in enumerate(zip(rows, shipped, strict=True)):
        movement = by_item.get(item.id)
        if movement is None:
            return False
        marker = f"idempotency:deliver:{key}:line:{index}"
        if (
            movement.tenant_id != tenant_id
            or movement.product_id != item.product_id
            or finite_decimal(movement.quantity) != -quantity
            or finite_decimal(movement.ordered_quantity) != quantity
            or finite_decimal(movement.delivered_quantity) != quantity
            or movement.reference_type != "sale_delivery"
            or movement.reference_id != order_id
            or not (
                movement.remark == marker or str(movement.remark or "").startswith(marker + " | ")
            )
            or movement.ledger_id is None
        ):
            return False
        previous = ledgers.get(movement.ledger_id)
        if previous is None or movement.id < previous.id:
            ledgers[movement.ledger_id] = movement
    for ledger_id, first in ledgers.items():
        ledger = (
            db.query(InventoryLedger)
            .filter(InventoryLedger.id == ledger_id, InventoryLedger.tenant_id == tenant_id)
            .one_or_none()
        )
        if ledger is None:
            return False
        quantity = finite_decimal(ledger.quantity)
        available = finite_decimal(ledger.available_quantity)
        reserved = finite_decimal(ledger.reserved_quantity)
        if (
            quantity is None
            or available is None
            or reserved is None
            or min(quantity, available, reserved) < 0
            or quantity != available + reserved
        ):
            return False
        running = finite_decimal(first.before_quantity)
        if running is None or running < 0:
            return False
        location_id = first.location_id
        valid_locations = {
            row[0]
            for row in db.query(StorageLocation.id).filter(
                StorageLocation.tenant_id == tenant_id,
                StorageLocation.warehouse_id == ledger.warehouse_id,
            )
        }
        if location_id is not None and location_id not in valid_locations:
            return False
        movements = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.ledger_id == ledger_id,
                InventoryTransaction.tenant_id == tenant_id,
                InventoryTransaction.id >= first.id,
            )
            .order_by(InventoryTransaction.id)
            .yield_per(1000)
        )
        for movement in movements:
            before = finite_decimal(movement.before_quantity)
            after = finite_decimal(movement.after_quantity)
            delta = finite_decimal(movement.quantity)
            # A confirmed stock count can relocate this same ledger. Subsequent
            # commands may omit their optional location; that does not erase the
            # original sale's recorded location or prove another relocation.
            if (
                movement.transaction_type == "count"
                and movement.reference_type == "inventory_count"
                and movement.location_id is not None
            ):
                if movement.location_id not in valid_locations:
                    return False
                location_id = movement.location_id
            if (
                movement.product_id != ledger.product_id
                or movement.warehouse_id != ledger.warehouse_id
                or (
                    (movement.id in original_movement_ids or movement.location_id is not None)
                    and movement.location_id != location_id
                )
                or movement.batch_no != ledger.batch_no
                or before is None
                or before != running
                or after is None
                or delta is None
                or after < 0
                or before + delta != after
            ):
                return False
            running = after
        if running != quantity or location_id != ledger.location_id:
            return False
    return True


def verify_closed_loop(payload: dict[str, Any], *, db: Session | None = None) -> dict[str, Any]:
    """Read back the committed sale. This step does not create or change business rows."""
    from app.application.agent_orchestrator.verification_transactions import (
        _journal,
    )
    from app.application.invoicing_service import find_sale_invoice_entry
    from app.application.sales.contracts import ClosedLoopExecutionError
    from app.application.sales.idempotency import (
        closed_loop_order_no,
        closed_loop_payment_key,
        composite_fingerprint,
        verify_fingerprint,
    )
    from app.application.sales.payment_verification import verified_sales_payment_total
    from app.application.sales.references import resolve_products, resolve_warehouse
    from app.application.sales.validation import (
        coerce_entity_id,
        reject_tenant_id,
        validate_arithmetic,
        validate_structure,
    )
    from app.db.models import (
        Customer,
        InventoryTransaction,
        ReceivableAllocation,
        SalesOrder,
        SalesOrderItem,
    )
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import TenantScopeError, tenant_id_for_write

    invalid = (
        validate_structure(payload) or reject_tenant_id(payload) or validate_arithmetic(payload)
    )
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
            .filter(
                SalesOrder.order_no == closed_loop_order_no(key, tenant_id),
                SalesOrder.tenant_id == tenant_id,
            )
            .one_or_none()
        )
        if saved is None:
            return {"success": False, "message": "未找到已提交的销售订单", "retryable": False}
        customer = (
            db.query(Customer)
            .filter(Customer.id == saved.customer_id, Customer.tenant_id == tenant_id)
            .one_or_none()
        )
        try:
            if customer is None or saved.customer_name != customer.customer_name:
                raise ClosedLoopExecutionError("verification", "批准客户与订单不一致")
            if order.get("customer_id") is not None:
                customer_matches = (
                    coerce_entity_id(order["customer_id"], "resolve_customer", "customer_id")
                    == customer.id
                )
            else:
                customer_matches = order.get("customer_name") == customer.customer_name
            if not customer_matches:
                raise ClosedLoopExecutionError("verification", "批准客户与订单不一致")
            products = resolve_products(db, order, tenant_id)
            warehouse = resolve_warehouse(db, payload["fulfillment"], tenant_id)
            fingerprint = composite_fingerprint(
                {"id": customer.id, "name": customer.customer_name},
                products,
                warehouse,
                order,
                payload["fulfillment"],
                payload["invoice"],
                payment,
            )
            verify_fingerprint(db, saved.id, fingerprint)
        except ClosedLoopExecutionError:
            return {"success": False, "message": "销售批准范围与账本不一致", "retryable": False}
        rows = (
            db.query(SalesOrderItem)
            .filter(SalesOrderItem.order_id == saved.id, SalesOrderItem.tenant_id == tenant_id)
            .order_by(SalesOrderItem.id)
            .all()
        )
        outs = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.sales_order_id == saved.id,
                InventoryTransaction.tenant_id == tenant_id,
                InventoryTransaction.transaction_type == "out",
            )
            .all()
        )
        invoice = find_sale_invoice_entry(db, saved.id) if invoice_requested else None
        paid = Decimal(str(saved.paid_amount or 0))
        quantity_ok = len(rows) == len(products) and all(
            row.product_id == product["product_id"]
            and row.product_name == product["product_name"]
            and row.unit == product["unit"]
            and finite_decimal(row.quantity) == product["quantity"]
            and finite_decimal(row.ordered_quantity) == product["quantity"]
            and finite_decimal(row.unit_price) == product["unit_price"]
            and finite_decimal(row.amount) == product["quantity"] * product["unit_price"]
            and finite_decimal(row.delivered_quantity) == shipped[index]
            and finite_decimal(row.returned_quantity) == 0
            for index, (row, product) in enumerate(zip(rows, products, strict=True))
        )
        amount_ok = (
            finite_decimal(saved.total_amount) == expected_amount
            and saved.currency == order["currency"]
            and saved.state == "confirmed"
        )
        stock_ok = (
            quantity_ok
            and all(movement.warehouse_id == warehouse["id"] for movement in outs)
            and _inventory_matches(db, tenant_id, saved.id, rows, outs, shipped, key)
        )
        invoice_ok = (
            invoice is not None
            and _journal(db, tenant_id, invoice.id, saved.id, "sale", expected_amount) is not None
            and saved.invoice_status == "invoiced"
            if invoice_requested
            else saved.invoice_status == "not_invoiced"
        )
        total_paid = verified_sales_payment_total(db, tenant_id, saved)
        if payment["requested"]:
            receipt = (
                db.query(ReceivableAllocation)
                .filter(
                    ReceivableAllocation.sales_order_id == saved.id,
                    ReceivableAllocation.tenant_id == tenant_id,
                    ReceivableAllocation.request_key == closed_loop_payment_key(key),
                    ReceivableAllocation.reference_type == "payment",
                )
                .one_or_none()
            )
            expected_payment = Decimal(str(payment["amount"]))
            payment_ok = (
                receipt is not None
                and receipt.status in {"partial", "paid"}
                and receipt.reference_id == saved.id
                and receipt.amount == expected_payment
                and receipt.allocated_amount == expected_payment
                and total_paid is not None
                and total_paid >= expected_payment
                and paid == total_paid
            )
        else:
            payment_ok = saved.payment_state == "unpaid" and paid == total_paid == 0
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
            "transaction_fingerprint": fingerprint,
        }


def verify_agent_closed_loop(
    step: Any, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Bind the original sales transaction receipt to current, read-only ledger evidence."""
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
    from app.application.sales.idempotency import closed_loop_payment_key
    from app.db.models import InventoryTransaction, ReceivableAllocation, SalesOrder

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
        approved = payload["order"]
        fingerprint = current["transaction_fingerprint"]
        items = sorted(order.items, key=lambda item: item.id)
        if (
            type(data.get("order_id")) is not int
            or data["order_id"] != order.id
            or data.get("order_no") != current["order_no"]
            or not isinstance(data.get("item_ids"), list)
            or any(type(item_id) is not int for item_id in data["item_ids"])
            or data.get("item_ids") != [item.id for item in items]
            or any(item.tenant_id != tenant for item in items)
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
