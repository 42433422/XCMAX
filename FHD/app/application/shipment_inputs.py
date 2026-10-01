"""Shipment inputs shared by clarification and execution."""

from typing import Any

from app.domain.shipment.aggregates import ShipmentItem


def missing_shipment_fields(params: dict[str, Any]) -> list[str]:
    missing = []
    unit = params.get("unit_name") or params.get("purchase_unit")
    if (
        not isinstance(unit, str)
        or not unit.strip()
        or unit.strip().casefold() in {"待用户提供", "待提供", "待填写", "tbd", "unknown"}
    ):
        missing.append("unit_name")
    products = params.get("products") or params.get("items")
    if not isinstance(products, list) or not products:
        return [*missing, "products"]
    for index, item in enumerate(products):
        try:
            if not isinstance(item, dict):
                raise ValueError("产品格式错误")
            ShipmentItem.from_dict(item)
        except (TypeError, ValueError, OverflowError):
            missing.append(f"products.{index}")
    return missing
