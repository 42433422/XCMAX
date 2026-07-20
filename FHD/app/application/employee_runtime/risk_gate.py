"""Employee-runtime compatibility facade for the domain autonomy guard."""

from __future__ import annotations

from typing import Any, Iterable

from app.domain.autonomy.autonomy_guard import evaluate_risk, get_autonomy_guard


def assess_risk(manifest: dict[str, Any], handlers: Iterable[str]) -> tuple[str, str]:
    level, reason = get_autonomy_guard().assess_employee_risk(manifest, handlers)
    return level.value, reason


def gate_action_or_block(
    employee_id: str,
    manifest: dict[str, Any],
    handlers: Iterable[str],
    input_data: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(input_data or {})
    level, inferred_reason = get_autonomy_guard().assess_employee_risk(
        manifest or {}, handlers, payload
    )
    action_name = (
        "code_write" if payload.get("tool") in {"patch_file", "write_file"} else "employee_execute"
    )
    decision = evaluate_risk(
        {
            "action": action_name,
            "risk_level": level.value,
            "action_id": str(payload.get("action_id") or ""),
            "rollback_path": "employee_compensating_action",
        },
        {
            **payload,
            "trigger": "employee_runtime",
        },
        action_id=str(payload.get("action_id") or "") or None,
        source=f"employee_runtime:{employee_id}",
    )
    result = {
        "ok": decision.allowed,
        "risk_level": decision.risk_level.value,
        "reason": f"{inferred_reason}; {decision.reason}",
        "decision": decision.decision,
        "action_id": decision.action_id,
    }
    if not decision.allowed:
        result.update(
            {
                "blocked": True,
                "pending_approval": decision.requires_confirmation,
                "detail": decision.reason,
            }
        )
    return result


__all__ = ["assess_risk", "gate_action_or_block"]
