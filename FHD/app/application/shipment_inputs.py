"""Shipment inputs shared by clarification and execution."""

import math
from typing import Any

_PLACEHOLDERS = {"待用户提供", "待提供", "待填写", "tbd", "unknown"}


def _provided_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().casefold() not in _PLACEHOLDERS
    )


def missing_shipment_fields(params: dict[str, Any]) -> list[str]:
    missing = []
    if not _provided_name(params.get("unit_name") or params.get("purchase_unit")):
        missing.append("unit_name")
    products = params.get("products") or params.get("items")
    if not isinstance(products, list) or not products:
        return [*missing, "products"]
    for index, item in enumerate(products):
        if not isinstance(item, dict):
            missing.append(f"products.{index}")
            continue
        if not _provided_name(item.get("product_name") or item.get("name")):
            missing.append(f"products.{index}.product_name")
        for key in ("quantity_tins", "tin_spec", "unit_price", "amount"):
            if key == "amount" and key not in item:
                continue
            value = item.get(key, item.get("spec_per_tin") if key == "tin_spec" else None)
            try:
                valid = not (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                    or (key in {"quantity_tins", "tin_spec"} and value <= 0)
                    or (key == "quantity_tins" and value != int(value))
                )
            except OverflowError:
                valid = False
            if not valid:
                missing.append(f"products.{index}.{key}")
    return missing


def resolve_shipment_product_source(
    payload: dict[str, Any], outputs: dict[str, Any]
) -> dict[str, Any]:
    """Freeze a unique completed product query into the approval parameters."""
    from app.domain.shipment.shipment_product_parser import _to_float_or_none

    payload = dict(payload)
    output = outputs.get(payload.pop("product_source_node", "")) or {}
    rows = output.get("data") if output.get("success") else []
    items = payload.get("products") or []
    if not isinstance(rows, list) or len(items) != 1 or not isinstance(items[0], dict):
        return payload
    item = dict(items[0])
    matches = [
        row for row in rows if isinstance(row, dict) and row.get("name") == item.get("product_name")
    ]
    if len(matches) == 1:
        for key, source in (("tin_spec", "specification"), ("unit_price", "price")):
            item.setdefault(key, _to_float_or_none(matches[0].get(source)))
        payload["products"] = [item]
    return payload
