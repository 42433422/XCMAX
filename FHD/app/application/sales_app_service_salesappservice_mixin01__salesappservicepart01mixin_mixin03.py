# mypy: disable-error-code="no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.sales_app_service")


class __SalesAppServicePart01MixinPart03Mixin:
    @staticmethod
    def _closed_loop_composite_fingerprint(
        customer: dict[str, _facade().Any],
        products: list[dict[str, _facade().Any]],
        warehouse: dict[str, _facade().Any],
        order: dict[str, _facade().Any],
        fulfillment: dict[str, _facade().Any],
        invoice: dict[str, _facade().Any],
        pa: dict[str, _facade().Any],
    ) -> str:
        """对解析后的完整复合业务载荷做冲突安全的 SHA-256 规范编码。

        覆盖：解析后的客户 ID/名称、产品 ID/名称/顺序/数量/单位/单价/行合计、
        订单币种/总额、解析后的仓库 ID、履行 requested/quantity/unit、
        开票 requested/amount/currency、收款分配 requested/amount/currency。
        """
        canonical = {
            "customer_id": customer["id"],
            "customer_name": customer["name"],
            "currency": order.get("currency"),
            "total_amount": _facade().SalesAppService._closed_loop_canon_dec(
                order.get("total_amount")
            ),
            "items": [
                {
                    "product_id": p["product_id"],
                    "product_name": p["product_name"],
                    "quantity": _facade().SalesAppService._closed_loop_canon_dec(p["quantity"]),
                    "unit": p["unit"],
                    "unit_price": _facade().SalesAppService._closed_loop_canon_dec(p["unit_price"]),
                    "line_total": _facade().SalesAppService._closed_loop_canon_dec(
                        _facade().Decimal(str(p["quantity"]))
                        * _facade().Decimal(str(p["unit_price"]))
                    ),
                }
                for p in products
            ],
            "warehouse_id": warehouse["id"],
            "fulfillment": {
                "requested": fulfillment.get("requested"),
                "quantity": _facade().SalesAppService._closed_loop_canon_dec(
                    fulfillment.get("quantity")
                ),
                "unit": fulfillment.get("unit"),
            },
            "invoice": {
                "requested": invoice.get("requested"),
                "amount": _facade().SalesAppService._closed_loop_canon_dec(invoice.get("amount")),
                "currency": invoice.get("currency"),
            },
            "payment_allocation": {
                "requested": pa.get("requested"),
                "amount": _facade().SalesAppService._closed_loop_canon_dec(pa.get("amount")),
                "currency": pa.get("currency"),
            },
        }
        canonical_str = _facade().json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return _facade().hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _closed_loop_extract_fingerprint(remark: str | None) -> str | None:
        """从既有 remark 字段中提取命名空间化的复合幂等指纹。"""
        if not remark:
            return None
        prefix = f"{_facade()._CLOSED_LOOP_FP_PREFIX}:"
        for part in remark.split("\n"):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix) :]
        return None

    def _closed_loop_verify_idempotent_fingerprint(
        self, db, order_id: int, fingerprint: str
    ) -> None:
        """同租户同 ``idempotency_key`` 但完整复合载荷指纹不一致 → fail-closed。

        在任一后续 confirm/deliver/invoice/payment 之前校验；不一致则抛出
        ``ClosedLoopExecutionError(step="idempotency")`` 触发外层事务整体回滚，
        绝不静默复用既有单，也不执行任何后续拥有方副作用。
        """
        order_obj = (
            db.query(_facade().SalesOrder).filter(_facade().SalesOrder.id == order_id).first()
        )
        if order_obj is None:
            raise _facade().ClosedLoopExecutionError("idempotency", "幂等订单读取失败")
        persisted = self._closed_loop_extract_fingerprint(order_obj.remark)
        if persisted is None or persisted != fingerprint:
            raise _facade().ClosedLoopExecutionError(
                "idempotency", "同 idempotency_key 但完整复合业务载荷与既有订单不一致，拒绝执行"
            )
