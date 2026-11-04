"""Pure payload validation and finite numeric conversion before any transaction writes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import ClosedLoopExecutionError


def to_decimal(value: Any) -> Decimal:
    """把报价数值安全转为 Decimal，保证账务全程定点运算、无浮点伪影。"""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal("0")


def validate_structure(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload:
        return {
            "success": False,
            "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
            "message": "缺少闭合载荷 payload",
        }
    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return {
            "success": False,
            "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
            "message": "闭合载荷缺少非空 idempotency_key",
        }
    for section in ("order", "fulfillment", "invoice", "payment_allocation"):
        sec = payload.get(section)
        if not isinstance(sec, dict) or not sec:
            return {
                "success": False,
                "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
                "message": f"闭合载荷缺少 dict 区块: {section}",
            }
    return None


def contains_tenant_id(value: Any) -> bool:
    if isinstance(value, dict):
        if "tenant_id" in value:
            return True
        return any(contains_tenant_id(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_tenant_id(v) for v in value)
    return False


def reject_tenant_id(payload: dict[str, Any]) -> dict[str, Any] | None:
    if contains_tenant_id(payload):
        return {
            "success": False,
            "error_code": "TENANT_ID_REJECTED",
            "message": "闭合载荷不允许调用方指定 tenant_id（零持久化）",
            "failed_step": "validation",
        }
    return None


def validate_arithmetic(payload: dict[str, Any]) -> dict[str, Any] | None:
    order = payload["order"]
    items = order.get("items")
    if not isinstance(items, list) or not items:
        return invalid_payload("order.items 缺失或为空")
    eps = Decimal("0.01")
    total = Decimal("0")
    total_qty = Decimal("0")
    units = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return invalid_payload(f"order.items[{idx}] 非 dict")
        qty = finite_decimal(item.get("quantity"))
        price = finite_decimal(item.get("unit_price"))
        line_total = finite_decimal(item.get("line_total"))
        if qty is None or price is None or line_total is None:
            return invalid_payload(f"order.items[{idx}] 数量/单价/合计非法")
        if qty <= 0 or price <= 0:
            return invalid_payload(f"order.items[{idx}] 数量或单价必须为正")
        unit = item.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            return invalid_payload(f"order.items[{idx}] 单位缺失")
        units.add(unit)
        if abs(line_total - qty * price) > eps:
            return invalid_payload(f"order.items[{idx}] line_total 与 数量*单价 不一致")
        total += line_total
        total_qty += qty
        if not item.get("product_id") and (
            not (item.get("product_name") and item.get("product_resolution"))
        ):
            return invalid_payload(f"order.items[{idx}] 缺少产品实体/解析方式")
    order_total = finite_decimal(order.get("total_amount"))
    if order_total is None:
        return invalid_payload("order.total_amount 非法")
    if abs(order_total - total) > eps:
        return invalid_payload("order.total_amount 与明细合计不一致")
    if not order.get("customer_id") and (
        not (order.get("customer_name") and order.get("customer_resolution"))
    ):
        return invalid_payload("order 缺少客户实体/解析方式")
    currency = order.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        return invalid_payload("order.currency 缺失")
    fulfillment = payload["fulfillment"]
    f_req = fulfillment.get("requested")
    if not isinstance(f_req, bool):
        return invalid_payload("fulfillment.requested 必须为 bool")
    if f_req is not True:
        return invalid_payload("fulfillment.requested 必须为 True（履行是契约必需）")
    f_qty = finite_decimal(fulfillment.get("quantity"))
    if f_qty is None:
        return invalid_payload("fulfillment.quantity 非法")
    if f_qty <= 0:
        return invalid_payload("fulfillment.quantity 必须为正")
    if abs(f_qty - total_qty) > eps:
        return invalid_payload("fulfillment.quantity 与订购总量不一致")
    f_unit = fulfillment.get("unit")
    if f_unit not in units:
        return invalid_payload("fulfillment.unit 与明细单位不一致")
    invoice = payload["invoice"]
    inv_req = invoice.get("requested")
    if not isinstance(inv_req, bool):
        return invalid_payload("invoice.requested 必须为 bool")
    if inv_req:
        inv_amt = finite_decimal(invoice.get("amount"))
        if inv_amt is None:
            return invalid_payload("invoice.amount 非法")
        if inv_amt <= 0:
            return invalid_payload("invoice.amount 必须为正")
        if abs(inv_amt - order_total) > eps:
            return invalid_payload("invoice.amount 与订单总额不一致")
        if invoice.get("currency") != currency:
            return invalid_payload("invoice.currency 与订单币种不一致")
    pa = payload["payment_allocation"]
    pa_req = pa.get("requested")
    if not isinstance(pa_req, bool):
        return invalid_payload("payment_allocation.requested 必须为 bool")
    if pa_req:
        pay_amt = finite_decimal(pa.get("amount"))
        if pay_amt is None:
            return invalid_payload("payment_allocation.amount 非法")
        if pay_amt <= 0:
            return invalid_payload("payment_allocation.amount 必须为正")
        if abs(pay_amt - order_total) > eps:
            return invalid_payload("payment_allocation.amount 与订单总额不一致")
        if pa.get("currency") != currency:
            return invalid_payload("payment_allocation.currency 与订单币种不一致")
    if inv_req is False and pa_req is True:
        return invalid_payload("invoice.requested=False 与 payment_allocation.requested=True 矛盾")
    return None


def invalid_payload(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": "INVALID_CLOSED_LOOP_PAYLOAD",
        "message": message,
        "failed_step": "validation",
    }


def finite_decimal(value: Any) -> Decimal | None:
    """安全地将载荷数值转为**有限** ``Decimal``。

    reject Python bool / None / NaN / Infinity / -Infinity，并捕获
    ``decimal.InvalidOperation``（含 ``TypeError/ValueError``），以确保任何
    畸形数值都返回结构化失败而非逃逸异常。
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    if not dec.is_finite():
        return None
    return dec


def coerce_entity_id(value: Any, step: str, label: str) -> int:
    """Reject lossy numeric conversion before an identifier reaches a database query."""
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not an entity identifier")
        identifier = int(value)
        if identifier <= 0 or (isinstance(value, (float, Decimal)) and value != identifier):
            raise ValueError("entity identifier must be a positive whole number")
    except (TypeError, ValueError, OverflowError):
        raise ClosedLoopExecutionError(step, f"{label} 非法: {value!r}") from None
    return identifier


def canonical_decimal(value: Any) -> str:
    """把数值规范化为无指数的定点字符串，保证指纹跨调用稳定。"""
    dec = finite_decimal(value)
    if dec is None:
        return "none"
    return format(dec, "f")
