"""Primitive coercion used while converting heterogeneous trace payloads."""

from __future__ import annotations

from typing import Any


def coerce_trace_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def coerce_trace_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
