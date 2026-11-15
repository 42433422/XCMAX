"""Pure shared scalar coercion; preserve the existing fallback contract."""

from __future__ import annotations

from typing import Any


def coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def coerce_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
