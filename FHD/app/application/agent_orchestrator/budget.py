from __future__ import annotations

from typing import Any

AI_COST_BUDGET_KEYS = (
    "ai_cost_budget_units",
    "cost_budget_units",
    "max_ai_cost_units",
    "budget_units",
)


def _coerce_budget_value(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(parsed, 0)


def extract_ai_cost_budget_units(*sources: dict[str, Any] | None) -> int | None:
    budget: int | None = None
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in AI_COST_BUDGET_KEYS:
            if key not in source:
                continue
            parsed = _coerce_budget_value(source.get(key))
            if parsed is not None:
                budget = parsed
    return budget


def refresh_ai_budget_metadata(run: Any) -> None:
    metadata = getattr(run, "metadata", None)
    if not isinstance(metadata, dict) or "ai_cost_budget_units" not in metadata:
        return
    budget = _coerce_budget_value(metadata.get("ai_cost_budget_units"))
    if budget is None:
        return
    total = _coerce_budget_value(metadata.get("ai_cost_units_total")) or 0
    metadata["ai_cost_budget_units"] = budget
    metadata["ai_cost_budget_remaining_units"] = max(budget - total, 0)
    metadata["ai_cost_budget_exceeded"] = total > budget


def apply_ai_budget_metadata(run: Any, *sources: dict[str, Any] | None) -> None:
    metadata = getattr(run, "metadata", None)
    if not isinstance(metadata, dict):
        return
    budget = extract_ai_cost_budget_units(*sources)
    if budget is not None:
        metadata["ai_cost_budget_units"] = budget
    refresh_ai_budget_metadata(run)


def budget_exceeded_payload(
    run: Any,
    *,
    additional_cost_units: int = 0,
    scope: str = "",
) -> dict[str, Any] | None:
    metadata = getattr(run, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    budget = _coerce_budget_value(metadata.get("ai_cost_budget_units"))
    if budget is None:
        return None
    current = _coerce_budget_value(metadata.get("ai_cost_units_total")) or 0
    additional = max(_coerce_budget_value(additional_cost_units) or 0, 0)
    projected = current + additional
    if projected <= budget:
        return None
    return {
        "error_code": "ai_cost_budget_exceeded",
        "message": "AI cost budget exceeded",
        "scope": str(scope or ""),
        "budget_units": budget,
        "current_units": current,
        "additional_cost_units": additional,
        "projected_units": projected,
        "remaining_units": max(budget - current, 0),
    }
