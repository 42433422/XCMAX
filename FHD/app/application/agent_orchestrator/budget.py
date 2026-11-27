from __future__ import annotations

from typing import Any

AI_COST_BUDGET_KEYS = (
    "ai_cost_budget_units",
    "cost_budget_units",
    "max_ai_cost_units",
    "budget_units",
)


def _coerce_budget_value(value: Any) -> int | None:
    if type(value) not in (int, float, str):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed < 0 or (isinstance(value, float) and value != parsed):
        return None
    return parsed


def _budget_constraints(*sources: dict[str, Any] | None) -> tuple[int | None, list[str]]:
    budgets: list[int] = []
    invalid: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in AI_COST_BUDGET_KEYS:
            value = source.get(key)
            if value is None:
                continue
            parsed = _coerce_budget_value(value)
            if parsed is None:
                invalid.add(key)
            budgets.append(parsed if parsed is not None else 0)
    return min(budgets, default=None), sorted(invalid)


def extract_ai_cost_budget_units(*sources: dict[str, Any] | None) -> int | None:
    """Aliases and source scopes are simultaneous ceilings, never overrides."""
    return _budget_constraints(*sources)[0]


def refresh_ai_budget_metadata(run: Any) -> None:
    apply_ai_budget_metadata(run)


def apply_ai_budget_metadata(run: Any, *sources: dict[str, Any] | None) -> None:
    """Ordinary resume can tighten a persisted budget, but cannot grant more credit."""
    metadata = getattr(run, "metadata", None)
    if not isinstance(metadata, dict):
        return
    budget, invalid = _budget_constraints(metadata, *sources)
    if budget is None:
        return
    if invalid:
        metadata["ai_cost_budget_invalid_fields"] = sorted(
            set(invalid) | set(metadata.get("ai_cost_budget_invalid_fields") or [])
        )
    total = _coerce_budget_value(metadata.get("ai_cost_units_total")) or 0
    metadata["ai_cost_budget_units"] = budget
    metadata["ai_cost_budget_remaining_units"] = max(budget - total, 0)
    metadata["ai_cost_budget_exceeded"] = (
        bool(metadata.get("ai_cost_budget_invalid_fields")) or total > budget
    )


def budget_exceeded_payload(
    run: Any,
    *,
    additional_cost_units: int = 0,
    scope: str = "",
) -> dict[str, Any] | None:
    metadata = getattr(run, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    budget, invalid = _budget_constraints(metadata)
    if budget is None:
        return None
    invalid = invalid or metadata.get("ai_cost_budget_invalid_fields") or []
    current = _coerce_budget_value(metadata.get("ai_cost_units_total")) or 0
    additional = max(_coerce_budget_value(additional_cost_units) or 0, 0)
    projected = current + additional
    if projected <= budget and not invalid:
        return None
    return {
        "error_code": "ai_cost_budget_invalid" if invalid else "ai_cost_budget_exceeded",
        "message": "AI cost budget is invalid" if invalid else "AI cost budget exceeded",
        "scope": str(scope or ""),
        "budget_units": budget,
        "current_units": current,
        "additional_cost_units": additional,
        "projected_units": projected,
        "remaining_units": max(budget - current, 0),
        **({"invalid_fields": invalid} if invalid else {}),
    }
