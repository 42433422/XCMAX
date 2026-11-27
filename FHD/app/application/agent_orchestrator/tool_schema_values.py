"""Primitive value predicates for the existing ToolSpec schema validator."""

from __future__ import annotations

from typing import Any


def type_matches(value: Any, expected: str | list[str]) -> bool:
    """Match declared JSON types without collapsing boolean and number."""
    if isinstance(expected, list):
        return any(isinstance(item, str) and type_matches(value, item) for item in expected)
    if expected == "null":
        return value is None
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


def allows_empty_value(value: Any, prop: Any) -> bool:
    """Only explicit null or zero-minimum text contracts admit empty scalars.

    This does not validate required-field presence or type constraints. The
    caller's single schema validator continues checking both independently.
    """
    if not isinstance(prop, dict):
        return False
    declared_type = prop.get("type")
    nullable = declared_type == "null" or (
        isinstance(declared_type, list) and "null" in declared_type
    )
    allows_empty_text = type(prop.get("minLength")) is int and prop["minLength"] == 0
    return (value is None and nullable) or (isinstance(value, str) and allows_empty_text)
