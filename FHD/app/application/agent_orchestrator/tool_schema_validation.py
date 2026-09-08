"""Shared tool payload validation, including explicitly allowed empty UI values."""

from __future__ import annotations

from typing import Any


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate_schema_payload(
    schema: dict[str, Any], payload: dict[str, Any], *, subject: str
) -> tuple[bool, str]:
    expected_root_type = str(schema.get("type") or "object").strip()
    if expected_root_type == "object" and not isinstance(payload, dict):
        return False, f"{subject} 必须是 object"
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if subject == "工具输出" and payload.get("success") is False:
        required = [key for key in (required or []) if str(key) == "success"]
    raw_properties = schema.get("properties")
    properties: dict[str, Any] = raw_properties if isinstance(raw_properties, dict) else {}
    for key in required or []:
        value = payload.get(str(key))
        prop = properties.get(str(key), {})
        prop = prop if isinstance(prop, dict) else {}
        empty_allowed = (
            isinstance(value, str)
            and prop.get("minLength") == 0
            or isinstance(value, list)
            and prop.get("minItems") == 0
        )
        if _is_empty(value) and not empty_allowed:
            return False, f"{subject} 缺少字段：{key}"
    for key, prop in properties.items():
        if key not in payload or _is_empty(payload.get(key)):
            continue
        if not isinstance(prop, dict):
            continue
        expected_type = str(prop.get("type") or "").strip()
        if expected_type and not _type_matches(payload.get(key), expected_type):
            return False, f"{subject} 字段 {key} 类型错误，应为 {expected_type}"
        value = payload.get(key)
        if isinstance(value, dict):
            valid, error = _validate_schema_payload(prop, value, subject=f"{subject}.{key}")
            if not valid:
                return False, error
        item_schema = prop.get("items")
        if isinstance(value, list) and isinstance(item_schema, dict):
            for index, item in enumerate(value):
                valid, error = _validate_schema_payload(
                    {"type": "object", "properties": {"item": item_schema}, "required": ["item"]},
                    {"item": item},
                    subject=f"{subject}.{key}[{index}]",
                )
                if not valid:
                    return False, error
        enum_values = prop.get("enum")
        if isinstance(enum_values, list) and enum_values and payload.get(key) not in enum_values:
            return False, f"{subject} 字段 {key} 不在允许范围内"
    return True, ""
