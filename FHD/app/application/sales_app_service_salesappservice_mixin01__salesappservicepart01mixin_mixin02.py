# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.sales_app_service")


class __SalesAppServicePart01MixinPart02Mixin:
    @staticmethod
    def _closed_loop_contains_tenant_id(value: _facade().Any) -> bool:
        if isinstance(value, dict):
            if "tenant_id" in value:
                return True
            return any(
                _facade().SalesAppService._closed_loop_contains_tenant_id(v) for v in value.values()
            )
        if isinstance(value, list):
            return any(_facade().SalesAppService._closed_loop_contains_tenant_id(v) for v in value)
        return False

    def _closed_loop_reject_tenant_id(
        self, payload: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any] | None:
        if self._closed_loop_contains_tenant_id(payload):
            return {
                "success": False,
                "error_code": "TENANT_ID_REJECTED",
                "message": "闭合载荷不允许调用方指定 tenant_id（零持久化）",
                "failed_step": "validation",
            }
        return None

    def _closed_loop_validate_arithmetic(
        self, payload: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any] | None:
        order = payload["order"]
        items = order.get("items")
        if not isinstance(items, list) or not items:
            return self._closed_loop_err("order.items 缺失或为空")
        eps = _facade().Decimal("0.01")
        total = _facade().Decimal("0")
        total_qty = _facade().Decimal("0")
        units = set()
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                return self._closed_loop_err(f"order.items[{idx}] 非 dict")
            qty = self._closed_loop_dec(item.get("quantity"))
            price = self._closed_loop_dec(item.get("unit_price"))
            line_total = self._closed_loop_dec(item.get("line_total"))
            if qty is None or price is None or line_total is None:
                return self._closed_loop_err(f"order.items[{idx}] 数量/单价/合计非法")
            if qty <= 0 or price <= 0:
                return self._closed_loop_err(f"order.items[{idx}] 数量或单价必须为正")
            unit = item.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                return self._closed_loop_err(f"order.items[{idx}] 单位缺失")
            units.add(unit)
            if abs(line_total - qty * price) > eps:
                return self._closed_loop_err(f"order.items[{idx}] line_total 与 数量*单价 不一致")
            total += line_total
            total_qty += qty
            if not item.get("product_id") and (
                not (item.get("product_name") and item.get("product_resolution"))
            ):
                return self._closed_loop_err(f"order.items[{idx}] 缺少产品实体/解析方式")
        order_total = self._closed_loop_dec(order.get("total_amount"))
        if order_total is None:
            return self._closed_loop_err("order.total_amount 非法")
        if abs(order_total - total) > eps:
            return self._closed_loop_err("order.total_amount 与明细合计不一致")
        if not order.get("customer_id") and (
            not (order.get("customer_name") and order.get("customer_resolution"))
        ):
            return self._closed_loop_err("order 缺少客户实体/解析方式")
        currency = order.get("currency")
        if not isinstance(currency, str) or not currency.strip():
            return self._closed_loop_err("order.currency 缺失")
        fulfillment = payload["fulfillment"]
        f_req = fulfillment.get("requested")
        if not isinstance(f_req, bool):
            return self._closed_loop_err("fulfillment.requested 必须为 bool")
        if f_req is not True:
            return self._closed_loop_err("fulfillment.requested 必须为 True（履行是契约必需）")
        f_qty = self._closed_loop_dec(fulfillment.get("quantity"))
        if f_qty is None:
            return self._closed_loop_err("fulfillment.quantity 非法")
        if f_qty <= 0:
            return self._closed_loop_err("fulfillment.quantity 必须为正")
        if abs(f_qty - total_qty) > eps:
            return self._closed_loop_err("fulfillment.quantity 与订购总量不一致")
        f_unit = fulfillment.get("unit")
        if f_unit not in units:
            return self._closed_loop_err("fulfillment.unit 与明细单位不一致")
        invoice = payload["invoice"]
        inv_req = invoice.get("requested")
        if not isinstance(inv_req, bool):
            return self._closed_loop_err("invoice.requested 必须为 bool")
        if inv_req:
            inv_amt = self._closed_loop_dec(invoice.get("amount"))
            if inv_amt is None:
                return self._closed_loop_err("invoice.amount 非法")
            if inv_amt <= 0:
                return self._closed_loop_err("invoice.amount 必须为正")
            if abs(inv_amt - order_total) > eps:
                return self._closed_loop_err("invoice.amount 与订单总额不一致")
            if invoice.get("currency") != currency:
                return self._closed_loop_err("invoice.currency 与订单币种不一致")
        pa = payload["payment_allocation"]
        pa_req = pa.get("requested")
        if not isinstance(pa_req, bool):
            return self._closed_loop_err("payment_allocation.requested 必须为 bool")
        if pa_req:
            pay_amt = self._closed_loop_dec(pa.get("amount"))
            if pay_amt is None:
                return self._closed_loop_err("payment_allocation.amount 非法")
            if pay_amt <= 0:
                return self._closed_loop_err("payment_allocation.amount 必须为正")
            if abs(pay_amt - order_total) > eps:
                return self._closed_loop_err("payment_allocation.amount 与订单总额不一致")
            if pa.get("currency") != currency:
                return self._closed_loop_err("payment_allocation.currency 与订单币种不一致")
        if inv_req is False and pa_req is True:
            return self._closed_loop_err(
                "invoice.requested=False 与 payment_allocation.requested=True 矛盾"
            )
        return None

    @staticmethod
    def _closed_loop_err(message: str) -> dict[str, _facade().Any]:
        return {
            "success": False,
            "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
            "message": message,
            "failed_step": "validation",
        }

    @staticmethod
    def _closed_loop_dec(value: _facade().Any) -> _facade().Decimal | None:
        """安全地将载荷数值转为**有限** ``Decimal``。

        reject Python bool / None / NaN / Infinity / -Infinity，并捕获
        ``decimal.InvalidOperation``（含 ``TypeError/ValueError``），以确保任何
        畸形数值都返回结构化失败而非逃逸异常。
        """
        if isinstance(value, bool) or value is None:
            return None
        try:
            dec = _facade().Decimal(str(value))
        except (TypeError, ValueError, _facade().InvalidOperation):
            return None
        if not dec.is_finite():
            return None
        return dec

    @staticmethod
    def _closed_loop_coerce_id(value: _facade().Any, step: str, label: str) -> int:
        """安全地把实体 id 转为 int；畸形 id（非数字字符串等）→ 结构化失败而非逃逸。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            raise _facade().ClosedLoopExecutionError(step, f"{label} 非法: {value!r}") from None

    @staticmethod
    def _closed_loop_order_no(idempotency_key: str, tenant_id: int) -> str:
        digest = _facade().hashlib.sha256(str(idempotency_key).encode("utf-8")).hexdigest()[:16]
        return f"CL{int(tenant_id)}-{digest}"

    def _closed_loop_run(
        self, db, payload: dict[str, _facade().Any], tenant_id: int, idempotency_key: str
    ) -> dict[str, _facade().Any]:
        order = payload["order"]
        fulfillment = payload["fulfillment"]
        invoice = payload["invoice"]
        pa = payload["payment_allocation"]
        customer = self._closed_loop_resolve_customer(db, order, tenant_id)
        products = self._closed_loop_resolve_products(db, order, tenant_id)
        warehouse = self._closed_loop_resolve_warehouse(db, fulfillment, tenant_id)
        fingerprint = self._closed_loop_composite_fingerprint(
            customer, products, warehouse, order, fulfillment, invoice, pa
        )
        order_no = self._closed_loop_order_no(idempotency_key, tenant_id)
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
        quote_res = self.quote(quote_data, db=db)
        if not quote_res.get("success"):
            raise _facade().ClosedLoopExecutionError(
                "quote", quote_res.get("message", "报价创建失败")
            )
        replayed = bool(quote_res.get("idempotent"))
        order_id = int(quote_res["data"]["id"])
        order_no = quote_res["data"]["order_no"]
        if replayed:
            self._closed_loop_verify_idempotent_fingerprint(db, order_id, fingerprint)
            inventory_sources = [{"batch_no": None, "location_id": None} for _product in products]
        else:
            self._closed_loop_persist_fingerprint(db, order_id, fingerprint)
            inventory_sources = [
                self._closed_loop_resolve_inventory_source(
                    db,
                    product_id=product["product_id"],
                    warehouse_id=warehouse["id"],
                    quantity=product["quantity"],
                    tenant_id=tenant_id,
                )
                for product in products
            ]
        confirm_res = self.confirm(order_id, db=db)
        if not confirm_res.get("success"):
            raise _facade().ClosedLoopExecutionError(
                "confirm", confirm_res.get("message", "确认销售订单失败")
            )
        order_items = (
            db.query(_facade().SalesOrderItem)
            .filter(_facade().SalesOrderItem.order_id == order_id)
            .order_by(_facade().SalesOrderItem.id.asc())
            .all()
        )
        item_ids = [oi.id for oi in order_items]
        fulfillment_results = []
        for idx, oi in enumerate(order_items):
            deliver_key = f"{idempotency_key}:line:{idx}"
            deliver_res = self.deliver(
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
            if not deliver_res.get("success"):
                raise _facade().ClosedLoopExecutionError(
                    "deliver", deliver_res.get("message", "交付失败")
                )
            fulfillment_results.append(deliver_res)
        invoice_entry_id = None
        if invoice.get("requested"):
            invoice_res = self.invoice(
                order_id, amount=self._closed_loop_dec(order.get("total_amount")), db=db
            )
            if not invoice_res.get("success"):
                raise _facade().ClosedLoopExecutionError(
                    "invoice", invoice_res.get("message", "开票失败")
                )
            invoice_entry_id = invoice_res.get("entry_id") or (invoice_res.get("data") or {}).get(
                "id"
            )
        payment_allocation_id = None
        if pa.get("requested"):
            payment_res = self.payment(
                order_id, amount=self._closed_loop_dec(order.get("total_amount")), db=db
            )
            if not payment_res.get("success"):
                raise _facade().ClosedLoopExecutionError(
                    "payment", payment_res.get("message", "收款失败")
                )
            payment_allocation_id = (payment_res.get("data") or {}).get("id")
        order_obj = (
            db.query(_facade().SalesOrder).filter(_facade().SalesOrder.id == order_id).first()
        )
        if order_obj is None:
            raise _facade().ClosedLoopExecutionError("postconditions", "订单后置条件读取失败")
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

    @staticmethod
    def _closed_loop_canon_dec(value: _facade().Any) -> str:
        """把数值规范化为无指数的定点字符串，保证指纹跨调用稳定。"""
        dec = _facade().SalesAppService._closed_loop_dec(value)
        if dec is None:
            return "none"
        return format(dec, "f")
