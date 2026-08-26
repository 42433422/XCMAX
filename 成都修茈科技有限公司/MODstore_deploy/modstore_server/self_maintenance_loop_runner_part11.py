# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _decide_post_loop_policy(
    *,
    branch: _facade().Optional[str],
    gate: _facade().Dict[str, _facade().Any],
    para_task_id: _facade().Optional[str],
    run_id: str,
    status: str,
    steps: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:

    def _hold_for_remediation(
        reason: str, **extra: _facade().Any
    ) -> _facade().Dict[str, _facade().Any]:
        return {"action": "hold_for_automated_remediation", "reason": reason, **extra}

    if status != "completed":
        return {"action": "stop", "reason": "loop_not_completed"}
    if any((not bool(step.get("ok")) for step in steps)):
        return {"action": "stop", "reason": "employee_step_failed"}
    structured_gate = _facade()._structured_report_gate(steps, branch)
    report_only_missing = _facade()._missing_report_only_evidence(steps)
    roster_gate = _facade()._loop_steps_roster_gate(steps)
    governance_gate = _facade()._governance_audit_gate()
    try:
        evolution_gate = _facade().evolution_metrics_gate()
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception(
            "failed to evaluate evolution metrics gate for policy active gates"
        )
        evolution_gate = {
            "pause": False,
            "reason": "metrics_gate_error",
            "error": str(exc)[:300],
            "history_count": 0,
        }
    active_gates = _facade()._policy_active_gates_snapshot(
        evolution_metrics=evolution_gate,
        gate=gate,
        governance_gate=governance_gate,
        report_only_missing=report_only_missing,
        roster_gate=roster_gate,
        structured_gate=structured_gate,
    )
    if structured_gate.get("ok") is False:
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
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_LOW_RISK", True):
        return _hold_for_remediation(
            "auto_merge_disabled",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
        )
    if structured_gate.get("ok") is not True:
        return _hold_for_remediation(
            structured_gate.get("reason") or "structured_report_gate_not_evaluated",
            active_gates=active_gates,
            evolution_gate=evolution_gate,
            governance_gate=governance_gate,
            roster_gate=roster_gate,
            structured_gate=structured_gate,
        )
    merge_result = _facade()._auto_merge_low_risk_branch(
        run_id=run_id, task_id=para_task_id, branch=branch, steps=steps
    )
    if merge_result.get("ok"):
        merge_requested = bool(merge_result.get("merge_requested"))
        deployment_receipt = (
            {"enabled": False, "reason": "merge_not_completed"}
            if merge_requested
            else _facade()._run_deploy_receipts_after_merge(
                run_id=run_id, merge_result=merge_result
            )
        )
        return {
            "action": (
                "auto_merge_requested_low_risk" if merge_requested else "auto_merged_low_risk"
            ),
            "active_gates": active_gates,
            "deployment_receipt": deployment_receipt,
            "evolution_gate": evolution_gate,
            "gate": gate,
            "governance_gate": governance_gate,
            "merge_result": merge_result,
            "reason": "low_risk_merge_requested" if merge_requested else "low_risk_policy_passed",
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
