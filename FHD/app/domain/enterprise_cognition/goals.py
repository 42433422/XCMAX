"""Comparable operating metrics and their binding errors; no persistence or execution."""

from decimal import Decimal, InvalidOperation
from typing import Any


class GoalBindingError(ValueError):
    """A goal lacks a comparable source or conflicts with an immutable binding."""


def metric_value(projection: dict[str, Any], metric: str, unit: str) -> Decimal:
    """Only compare a direct, finite authoritative value with an explicit unit."""
    if projection.get("freshness") != "fresh" or not projection.get("source_version"):
        raise GoalBindingError("entity_state_unavailable")
    state = projection.get("state")
    if not isinstance(state, dict):
        raise GoalBindingError("entity_state_unavailable")
    value = state.get(metric)
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise GoalBindingError("metric_not_numeric")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise GoalBindingError("metric_not_numeric") from exc
    if not number.is_finite():
        raise GoalBindingError("metric_not_finite")
    units = state.get("metric_units")
    declared = units.get(metric) if isinstance(units, dict) else None
    if metric.endswith("quantity"):
        declared = state.get("quantity_unit")
    elif metric.endswith("amount"):
        declared = state.get("currency")
    if not declared or declared != unit:
        raise GoalBindingError("metric_unit_unknown_or_mismatched")
    return number
