"""Single-transaction sales orchestration over explicit domain service ports."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import SalesOrder, SalesOrderItem

from .contracts import ClosedLoopExecutionError, FingerprintPorts, ReferencePorts, SalesOperations
from .idempotency import closed_loop_order_no, verify_payment_replay
from .validation import finite_decimal


def require_success(result: dict[str, Any], step: str, default_message: str) -> None:
    if not result.get("success"):
        raise ClosedLoopExecutionError(step, result.get("message", default_message))


class ClosedLoopRunner:
    def __init__(
        self,
        operations: SalesOperations,
        references: ReferencePorts,
        fingerprints: FingerprintPorts,
    ) -> None:
        self._operations = operations
        self._references = references
        self._fingerprints = fingerprints

    def run(
        self, db: Session, payload: dict[str, Any], tenant_id: int, idempotency_key: str
    ) -> dict[str, Any]:
        order = payload["order"]
        fulfillment = payload["fulfillment"]
        invoice = payload["invoice"]
        pa = payload["payment_allocation"]
        payment_key = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        customer = self._references.customer(db, order, tenant_id)
        products = self._references.products(db, order, tenant_id)
        warehouse = self._references.warehouse(db, fulfillment, tenant_id)
        fingerprint = self._fingerprints.build(
            customer, products, warehouse, order, fulfillment, invoice, pa
        )
        order_no = closed_loop_order_no(idempotency_key, tenant_id)
        quote_data = {
            "customer_id": customer["id"],
            "items": [
                {
                    "product_id": p["product_id"],
                    "quantity": p["quantity"],
                    "unit_price": p["unit_price"],
                    "unit": p["unit"],
                    "product_name": p["product_name"],
                }
                for p in products
            ],
            "order_no": order_no,
            "idempotency_key": idempotency_key,
            "currency": order.get("currency", "CNY"),
        }
        quote_res = self._operations.quote(quote_data, db=db)
        require_success(quote_res, "quote", "报价创建失败")
        replayed = bool(quote_res.get("idempotent"))
        order_id = int(quote_res["data"]["id"])
        order_no = quote_res["data"]["order_no"]
        if replayed:
            self._fingerprints.verify(db, order_id, fingerprint)
            if pa.get("requested"):
                verify_payment_replay(db, order_id, payment_key, tenant_id)
            inventory_sources = [{"batch_no": None, "location_id": None} for _product in products]
        else:
            self._fingerprints.persist(db, order_id, fingerprint)
            inventory_sources = [
                self._references.inventory(
                    db,
                    product_id=product["product_id"],
                    warehouse_id=warehouse["id"],
                    quantity=product["quantity"],
                    tenant_id=tenant_id,
                )
                for product in products
            ]
        confirm_res = self._operations.confirm(order_id, db=db)
        require_success(confirm_res, "confirm", "确认销售订单失败")
        order_items = (
            db.query(SalesOrderItem)
            .filter(SalesOrderItem.order_id == order_id)
            .order_by(SalesOrderItem.id.asc())
            .all()
        )
        item_ids = [oi.id for oi in order_items]
        fulfillment_results = []
        for idx, oi in enumerate(order_items):
            deliver_key = f"{idempotency_key}:line:{idx}"
            deliver_res = self._operations.deliver(
                order_id,
                oi.id,
                oi.quantity,
                warehouse_id=warehouse["id"],
                product_id=oi.product_id,
                batch_no=inventory_sources[idx]["batch_no"],
                location_id=inventory_sources[idx]["location_id"],
                idempotency_key=deliver_key,
                db=db,
            )
            require_success(deliver_res, "deliver", "交付失败")
            fulfillment_results.append(deliver_res)
        invoice_entry_id = None
        if invoice.get("requested"):
            invoice_res = self._operations.invoice(
                order_id, amount=finite_decimal(order.get("total_amount")), db=db
            )
            require_success(invoice_res, "invoice", "开票失败")
            invoice_entry_id = invoice_res.get("entry_id") or (invoice_res.get("data") or {}).get(
                "id"
            )
        payment_allocation_id = None
        if pa.get("requested"):
            payment_res = self._operations.payment(
                order_id,
                amount=finite_decimal(order.get("total_amount")),
                db=db,
                idempotency_key=payment_key,
            )
            require_success(payment_res, "payment", "收款失败")
            payment_allocation_id = (payment_res.get("data") or {}).get("id")
        order_obj = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
        if order_obj is None:
            raise ClosedLoopExecutionError("postconditions", "订单后置条件读取失败")
        return {
            "success": True,
            "idempotency_key": idempotency_key,
            "replayed": replayed,
            "data": {
                "order_id": order_id,
                "order_no": order_no,
                "item_ids": item_ids,
                "fulfillment": fulfillment_results,
                "invoice_entry_id": invoice_entry_id,
                "payment_allocation_id": payment_allocation_id,
                "postconditions": {
                    "state": order_obj.state,
                    "fulfillment": order_obj.fulfillment_state(),
                    "invoice_status": order_obj.invoice_status,
                    "payment_state": order_obj.payment_state,
                    "total_amount": float(order_obj.total_amount)
                    if order_obj.total_amount is not None
                    else 0.0,
                    "paid_amount": float(order_obj.paid_amount)
                    if order_obj.paid_amount is not None
                    else 0.0,
                },
            },
        }
