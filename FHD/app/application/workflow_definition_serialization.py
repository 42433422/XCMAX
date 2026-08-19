"""Serialization helpers shared by workflow-definition persistence operations."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


def coerce_serializable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [coerce_serializable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): coerce_serializable(item) for key, item in value.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return {
            key: coerce_serializable(item)
            for key, item in value.__dict__.items()
            if not key.startswith("_")
        }
    return str(value)


__all__ = ["coerce_serializable"]
