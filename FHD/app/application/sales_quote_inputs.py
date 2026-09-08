"""Validate quote quantities and prices before any order is added to a session."""

from decimal import Decimal, InvalidOperation
from typing import Any


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
