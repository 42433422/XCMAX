"""Pure sales-write admission and stable idempotency keys."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

_SALES_WRITE_SELL_MARKERS = ("卖给", "销售给", "出售给")


def _as_closed_loop_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def _sales_write_idempotency_key(
    customer_name: str,
    product_name: str,
    quantity: int | float,
    unit: str,
    unit_price: int | float,
    request_invoice: bool,
    request_payment: bool,
) -> str:
    seed = json.dumps(
        {
            "customer_name": customer_name,
            "product_name": product_name,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "invoice": request_invoice,
            "payment": request_payment,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sw-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _first_marker(text: str, markers: tuple[str, ...], start: int = 0) -> tuple[int, str]:
    matches = ((index, marker) for marker in markers if (index := text.find(marker, start)) >= 0)
    return min(matches, default=(-1, ""), key=lambda item: item[0])


def _decimal_prefix(text: str) -> tuple[float, str] | None:
    candidate = text.lstrip()
    allowed = "+-.0123456789"
    end = next(
        (index for index, char in enumerate(candidate) if char not in allowed), len(candidate)
    )
    try:
        value = float(candidate[:end])
        return (value, candidate[end:]) if math.isfinite(value) else None
    except ValueError:
        return None


def _parse_sales_write_request(text: str) -> dict[str, Any] | None:
    """线性解析销售闭环写意图；字段缺失或非正时 fail closed。"""
    if not any(marker in text for marker in _SALES_WRITE_SELL_MARKERS):
        return None
    head_index, head_marker = _first_marker(text, ("把", "将"))
    if head_index < 0:
        return None
    product_start = head_index + len(head_marker)
    sell_index, sell_marker = _first_marker(text, _SALES_WRITE_SELL_MARKERS, product_start)
    if sell_index < 0:
        return None
    customer_start = sell_index + len(sell_marker)
    delimiter_index, _ = _first_marker(text, tuple("，,；;"), customer_start)
    if delimiter_index < 0:
        return None
    product_name = text[product_start:sell_index].strip()
    customer_name = text[customer_start:delimiter_index].strip()
    if not product_name or not customer_name:
        return None
    tail = text[delimiter_index + 1 :]
    quantity_scan = _decimal_prefix(tail)
    if quantity_scan is None:
        return None
    quantity_raw, quantity_tail = quantity_scan
    unit_text = quantity_tail.lstrip()
    unit_end = next(
        (
            index
            for index, char in enumerate(unit_text)
            if char.isdigit() or char.isspace() or char in "，,。；;"
        ),
        len(unit_text),
    )
    unit = unit_text[:unit_end]
    if not 1 <= len(unit) <= 4:
        return None
    price_marker = tail.find("单价")
    if price_marker < 0:
        return None
    price_text = tail[price_marker + len("单价") :].lstrip(" \t\r\n:：")
    price_scan = _decimal_prefix(price_text)
    if price_scan is None:
        return None
    unit_price_raw, _price_tail = price_scan
    if quantity_raw <= 0 or unit_price_raw <= 0 or (not unit):
        return None
    if not math.isfinite(quantity_raw * unit_price_raw):
        return None
    quantity = _as_closed_loop_number(quantity_raw)
    unit_price = _as_closed_loop_number(unit_price_raw)
    total_amount = _as_closed_loop_number(quantity_raw * unit_price_raw)
    request_invoice = "开票" in text
    request_payment = "收款" in text
    idem_key = _sales_write_idempotency_key(
        customer_name, product_name, quantity, unit, unit_price, request_invoice, request_payment
    )
    return {
        "idempotency_key": idem_key,
        "order": {
            "customer_name": customer_name,
            "customer_id": None,
            "customer_resolution": "current_tenant_exact_name",
            "currency": "CNY",
            "items": [
                {
                    "product_name": product_name,
                    "product_id": None,
                    "product_resolution": "current_tenant_exact_name",
                    "quantity": quantity,
                    "unit": unit,
                    "unit_price": unit_price,
                    "line_total": total_amount,
                }
            ],
            "total_amount": total_amount,
        },
        "fulfillment": {
            "requested": True,
            "quantity": quantity,
            "unit": unit,
            "warehouse_id": None,
            "warehouse_resolution": "current_tenant_default",
        },
        "invoice": {"requested": request_invoice, "amount": total_amount, "currency": "CNY"},
        "payment_allocation": {
            "requested": request_payment,
            "amount": total_amount,
            "currency": "CNY",
        },
    }


def _is_sales_closed_loop_write(text: str) -> bool:
    """供规则规划器复用同源、无副作用的销售闭环写判定。"""
    return _parse_sales_write_request(text) is not None
