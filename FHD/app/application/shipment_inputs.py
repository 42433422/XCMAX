import math
from typing import Any

_PLACEHOLDERS = {"待用户提供", "待提供", "待填写", "tbd", "unknown"}
_PLACEHOLDERS.update(("用户需提供", "需要用户提供", "请用户提供"))


def _provided_name(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return value.strip().casefold() not in _PLACEHOLDERS and "{{" not in value


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
                valid = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    and value >= 0
                    and (key not in {"quantity_tins", "tin_spec"} or value > 0)
                    and (key != "quantity_tins" or value == int(value))
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


def shipment_call_payload(tool_id: str, action: str, params: dict) -> dict | None:
    if (tool_id, action) == ("shipment_records", "create"):
        return params
    if tool_id == "business_db" and action == "write":
        from app.services.tools_workflow_common import _normalize_business_db_entity

        if (
            _normalize_business_db_entity(params.get("entity")) == "shipment_records"
            and str(params.get("operation") or params.get("op") or "create").lower() == "create"
        ):
            return params.get("payload") if isinstance(params.get("payload"), dict) else {}
    return None


def missing_shipment_call_fields(tool_id: str, action: str, params: dict) -> list[str]:
    payload = shipment_call_payload(tool_id, action, params)
    missing = missing_shipment_fields(payload) if payload is not None else []
    if (
        payload
        and isinstance(payload.get("product_source_node"), str)
        and payload["product_source_node"].strip()
    ):
        missing = [
            key for key in missing if key not in {"products.0.tin_spec", "products.0.unit_price"}
        ]
    return missing
