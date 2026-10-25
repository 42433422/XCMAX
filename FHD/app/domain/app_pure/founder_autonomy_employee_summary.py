"""Employee evidence projection for the founder-autonomy live summary."""

from __future__ import annotations

from typing import Any, Mapping


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_employee_live_summary(
    employee_capability: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Return capability, burn-in, and production-duty evidence without relabeling."""

    return {
        "planned_employees": _as_int(facts.get("planned")),
        "registered_employees": _as_int(facts.get("registered")),
        "assigned_employees": _as_int(facts.get("assigned_employees")),
        "proven_employees": _as_int(facts.get("proven_employees")),
        "burn_in_proven_employees": _as_int(facts.get("burn_in_proven_employees")),
        "production_proven_employees": _as_int(facts.get("production_proven_employees")),
        "shell_employees": _as_int(facts.get("shell_employees")),
        "employee_workforce_ready": bool(facts.get("workforce_ready")),
        "employee_production_workforce_ready": bool(facts.get("production_workforce_ready")),
        "employee_assignment_ratio": _as_float(employee_capability.get("assignment_ratio")),
        "employee_proof_ratio": _as_float(employee_capability.get("proof_ratio")),
        "employee_burn_in_proof_ratio": _as_float(employee_capability.get("burn_in_proof_ratio")),
        "employee_production_proof_ratio": _as_float(
            employee_capability.get("production_proof_ratio")
        ),
        "employee_production_window_hours": _as_int(
            employee_capability.get("production_window_hours")
        ),
        "platform_llm": (
            dict(employee_capability.get("platform_llm") or {})
            if isinstance(employee_capability.get("platform_llm"), dict)
            else {}
        ),
    }


__all__ = ["build_employee_live_summary"]
