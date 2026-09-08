"""Validate quote quantities and prices before any order is added to a session."""

from decimal import Decimal, InvalidOperation
from typing import Any


def missing_quote_fields(data: dict[str, Any]) -> list[str]:
    missing = []
    if data.get("customer_id") in (None, "") and not str(data.get("customer_name") or "").strip():
        missing.append("customer_name")
    if data.get("items") in (None, [], {}):
        missing.append("items")
    return missing


def validated_quote_request(data: dict[str, Any]) -> list[dict[str, Any]]:
    missing = missing_quote_fields(data)
    if missing:
        raise ValueError("缺少报价参数：" + "、".join(missing))
    customer_id = data.get("customer_id")
    if customer_id not in (None, ""):
        if isinstance(customer_id, bool) or not str(customer_id).isdigit() or int(customer_id) <= 0:
            raise ValueError("客户编号必须是正整数")
    if "customer_name" in data and not isinstance(data["customer_name"], str):
        raise ValueError("客户名称必须是文本")
    if not isinstance(data.get("items"), list):
        raise ValueError("报价明细必须是列表")
    return validated_quote_items(data["items"])


def validated_quote_items(items: list[Any]) -> list[dict[str, Any]]:
    validated = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项报价明细格式错误")
        values = dict(item)
        for field, label in (("quantity", "数量"), ("unit_price", "单价")):
            raw = item.get(field)
            if raw is None or isinstance(raw, bool):
                raise ValueError(f"第 {index} 项缺少有效{label}")
            try:
                number = Decimal(str(raw))
            except (ValueError, InvalidOperation):
                raise ValueError(f"第 {index} 项{label}必须是有效数字") from None
            if not number.is_finite() or number < 0 or (field == "quantity" and number == 0):
                raise ValueError(f"第 {index} 项{label}超出允许范围")
            values[field] = number
        validated.append(values)
    return validated
