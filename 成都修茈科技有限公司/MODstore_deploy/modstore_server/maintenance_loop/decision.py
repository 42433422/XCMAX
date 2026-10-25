"""Apply structured, roster, governance and evolution gates in order."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modstore_server import self_evolution_knowledge
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, deployment, governance, merge, review


def _decide_post_loop_policy(
    *,
    branch: Optional[str],
    gate: Dict[str, Any],
    para_task_id: Optional[str],
    run_id: str,
    status: str,
    steps: List[Dict[str, Any]],
) -> Dict[str, Any]:

    def _hold_for_remediation(reason: str, **extra: Any) -> Dict[str, Any]:
        return {"action": "hold_for_automated_remediation", "reason": reason, **extra}

    if status != "completed":
        return {"action": "stop", "reason": "loop_not_completed"}
    if any((not bool(step.get("ok")) for step in steps)):
        return {"action": "stop", "reason": "employee_step_failed"}
    structured_gate = review._structured_report_gate(steps, branch)
    report_only_missing = review._missing_report_only_evidence(steps)
    roster_gate = governance._loop_steps_roster_gate(steps)
    governance_gate = governance._governance_audit_gate()
    try:
        evolution_gate = self_evolution_knowledge.evolution_metrics_gate()
    except RECOVERABLE_ERRORS as exc:
        config.logger.exception(
            "failed to evaluate evolution metrics gate for policy active gates"
        )
        evolution_gate = {
            "pause": False,
            "reason": "metrics_gate_error",
            "error": str(exc)[:300],
            "history_count": 0,
        }
    active_gates = governance._policy_active_gates_snapshot(
        evolution_metrics=evolution_gate,
        gate=gate,
        governance_gate=governance_gate,
        report_only_missing=report_only_missing,
        roster_gate=roster_gate,
        structured_gate=structured_gate,
    )
    if not structured_gate.get("ok"):
        return _hold_for_remediation(
            structured_gate.get("reason") or "structured_report_gate_failed",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
            structured_gate=structured_gate,
        )
    if report_only_missing:
        return _hold_for_remediation(
            "missing_report_only_evidence",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not roster_gate.get("ok"):
        return _hold_for_remediation(
            roster_gate.get("reason") or "roster_gate_failed",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not governance_gate.get("ok"):
        return _hold_for_remediation(
            governance_gate.get("reason") or "governance_gate_failed",
            active_gates=active_gates,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if bool(evolution_gate.get("pause")):
        return _hold_for_remediation(
            evolution_gate.get("reason") or "evolution_metrics_pause",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if not branch:
        return {
            "action": "auto_continue",
            "active_gates": active_gates,
            "evolution_gate": evolution_gate,
            "governance_gate": governance_gate,
            "reason": "no_code_branch",
            "roster_gate": roster_gate,
        }
    if not config._env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True):
        return _hold_for_remediation(
            "auto_merge_disabled",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    merge_result = merge._auto_merge_low_risk_branch(
        run_id=run_id, task_id=para_task_id, branch=branch, steps=steps
    )
    if merge_result.get("ok"):
        merge_requested = bool(merge_result.get("merge_requested"))
        deployment_receipt = (
            {"enabled": False, "reason": "merge_not_completed"}
            if merge_requested
            else deployment._run_deploy_receipts_after_merge(
                run_id=run_id, merge_result=merge_result
            )
        )
        return {
            "action": (
                "auto_merge_requested_low_risk"
                if merge_requested
                else "auto_merged_low_risk"
            ),
            "active_gates": active_gates,
            "deployment_receipt": deployment_receipt,
            "evolution_gate": evolution_gate,
            "gate": gate,
            "governance_gate": governance_gate,
            "merge_result": merge_result,
            "reason": "low_risk_merge_requested"
            if merge_requested
            else "low_risk_policy_passed",
            "roster_gate": roster_gate,
        }
    return _hold_for_remediation(
        merge_result.get("reason") or "auto_merge_not_allowed",
        gate=gate,
        active_gates=active_gates,
        evolution_gate=evolution_gate,
        governance_gate=governance_gate,
        merge_result=merge_result,
        roster_gate=roster_gate,
    )
