"""Validate quote quantities and prices before any order is added to a session."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any


def missing_quote_fields(data: dict[str, Any]) -> list[str]:
    missing = []
    if data.get("customer_id") in (None, "") and not str(data.get("customer_name") or "").strip():
        missing.append("customer_name")
    if data.get("items") in (None, [], {}):
        missing.append("items")
    elif isinstance(data.get("items"), list):
        for index, item in enumerate(data["items"]):
            if isinstance(item, dict):
                for field in ("quantity", "unit_price"):
                    if item.get(field) in (None, ""):
                        missing.append(f"items.{index}.{field}")
    return missing


def quote_answer_candidate(data: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    if not answers or not set(answers) <= set(missing_quote_fields(data)):
        raise ValueError("只能补充当前报价缺失的字段")
    candidate = deepcopy(data)
    for key, value in answers.items():
        if key.startswith("items."):
            _, index, field = key.split(".")
            candidate["items"][int(index)][field] = deepcopy(value)
        else:
            candidate[key] = deepcopy(value)
    return candidate


def quote_question_fields(data: dict[str, Any]) -> list[dict[str, str]]:
    fields = []
    for key in missing_quote_fields(data):
        if key.startswith("items."):
            _, index, field = key.split(".")
            item = data["items"][int(index)]
            product = (
                item.get("model_number") or item.get("product_name") or f"第 {int(index) + 1} 项"
            )
            label = "数量" if field == "quantity" else "单价"
            fields.append({"key": key, "label": f"{product} · {label}", "type": "number"})
        else:
            fields.append(
                {
                    "key": key,
                    "label": "客户名称" if key == "customer_name" else "报价明细",
                    "type": "string" if key == "customer_name" else "array",
                }
            )
    return fields


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
