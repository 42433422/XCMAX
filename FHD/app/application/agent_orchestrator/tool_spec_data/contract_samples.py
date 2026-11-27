"""Generate deterministic example payloads for tool contract fixtures."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _sample_value_for_property(key: str, prop: dict[str, Any]) -> Any:
    if "default" in prop:
        return deepcopy(prop["default"])
    choices = prop.get("anyOf")
    if isinstance(choices, list) and choices:
        return _sample_value_for_property(key, choices[0])
    enum_values = prop.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    expected_type = str(prop.get("type") or "").strip()
    if key == "success":
        return True
    if key in {"ids", "records", "artifacts", "data"} and expected_type == "array":
        return [{"sample": True}]
    if key == "payload":
        return {"sample": True}
    if key in {"created_customers", "created_products", "imported_count"}:
        return 1
    if key == "download_url":
        return "/api/sample/download"
    if key == "file_name":
        return "sample.docx"
    if expected_type == "object":
        if prop.get("properties"):
            return _sample_payload_from_schema(prop)
        if isinstance(prop.get("additionalProperties"), dict):
            return {"sample": _sample_value_for_property("sample", prop["additionalProperties"])}
        return {"sample": True}
    if expected_type == "array":
        raw_items = prop.get("items")
        items = raw_items if isinstance(raw_items, dict) else {}
        if str(items.get("type") or "").strip() == "string":
            return [f"sample_{key}"]
        if items.get("properties"):
            return [_sample_payload_from_schema(items)]
        return [{"sample": True}]
    if expected_type == "integer":
        return 1
    if expected_type == "number":
        return 1.0
    if expected_type == "boolean":
        return True
    return f"sample_{key}"


def _sample_payload_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    payload: dict[str, Any] = {}
    for key, prop in (properties or {}).items():
        payload[str(key)] = _sample_value_for_property(
            str(key), prop if isinstance(prop, dict) else {}
        )
    for key in required or []:
        normalized_key = str(key)
        if normalized_key not in payload:
            payload[normalized_key] = f"sample_{normalized_key}"
    return payload


def _default_fixture(
    tool_id: str,
    action: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "name": f"{tool_id}.{action}.contract",
            "input": _sample_payload_from_schema(input_schema),
            "output": _sample_payload_from_schema(output_schema),
        }
    ]
