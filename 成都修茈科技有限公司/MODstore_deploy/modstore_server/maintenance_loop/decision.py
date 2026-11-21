"""Apply structured, roster, governance and evolution gates in order."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from modstore_server import self_evolution_knowledge
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, deployment, governance, merge, review


def _prepare_post_loop_policy(*, gate: dict, policy_override: Optional[dict] = None) -> dict:
    """Freeze the no-effects stage before policy reads or external merge intent."""
    return {
        "stage": "before_policy",
        "policy": {"gate": gate, "deployment_scope": deployment._deployment_scope()},
        **({"policy_override": policy_override} if policy_override is not None else {}),
    }


def _decide_post_loop_policy(
    *,
    branch: Optional[str],
    gate: Dict[str, Any],
    para_task_id: Optional[str],
    run_id: str,
    status: str,
    steps: List[Dict[str, Any]],
    checkpoint: Optional[Callable[[dict], None]] = None,
    frozen_scope: Optional[dict] = None,
) -> Dict[str, Any]:

    def _hold_for_remediation(reason: str, **extra: Any) -> Dict[str, Any]:
        return {"action": "hold_for_automated_remediation", "reason": reason, **extra}

    if status != "completed":
        return {"action": "stop", "reason": "loop_not_completed"}
    if any((not bool(step.get("ok")) for step in steps)):
        return {"action": "stop", "reason": "employee_step_failed"}
    scope = deployment._deployment_scope()
    if frozen_scope is not None and frozen_scope != scope:
        raise ValueError("original_deployment_scope_changed")
    structured_gate = review._structured_report_gate(steps, branch)
    report_only_missing = review._missing_report_only_evidence(steps)
    roster_gate = governance._loop_steps_roster_gate(steps)
    governance_gate = governance._governance_audit_gate()
    try:
        evolution_gate = self_evolution_knowledge.evolution_metrics_gate()
    except RECOVERABLE_ERRORS as exc:
        config.logger.exception("failed to evaluate evolution metrics gate for policy active gates")
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
    policy = {
        "active_gates": active_gates,
        "evolution_gate": evolution_gate,
        "gate": gate,
        "governance_gate": governance_gate,
        "roster_gate": roster_gate,
        "deployment_scope": scope,
    }
    merge_result = merge._auto_merge_low_risk_branch(
        run_id=run_id,
        task_id=para_task_id,
        branch=branch,
        steps=steps,
        **(
            {
                "checkpoint": lambda intent: checkpoint(
                    {"stage": "merge_intent", "policy": policy, "intent": intent}
                ),
                "deployment_scope": policy["deployment_scope"],
            }
            if checkpoint is not None
            else {}
        ),
    )
    if merge_result.get("ok"):
        merge_requested = bool(merge_result.get("merge_requested"))
        policy = {
            **policy,
            "action": (
                "auto_merge_requested_low_risk" if merge_requested else "auto_merged_low_risk"
            ),
            "merge_result": merge_result,
            "reason": ("low_risk_merge_requested" if merge_requested else "low_risk_policy_passed"),
        }
        if checkpoint is not None:
            checkpoint({"stage": "merge_observed", "policy": policy})
        return _complete_merge_policy(run_id, policy, checkpoint=checkpoint)
    return _hold_for_remediation(
        merge_result.get("reason") or "auto_merge_not_allowed",
        gate=gate,
        active_gates=active_gates,
        evolution_gate=evolution_gate,
        governance_gate=governance_gate,
        merge_result=merge_result,
        roster_gate=roster_gate,
    )


def _complete_merge_policy(
    run_id: str, policy: dict, *, checkpoint: Optional[Callable[[dict], None]] = None
) -> dict:
    if policy.get("deployment_scope") != deployment._deployment_scope():
        raise ValueError("original_deployment_scope_changed")
    result = policy["merge_result"]
    receipt: dict[str, Any] = (
        {"enabled": False, "reason": "merge_not_completed"}
        if result.get("merge_requested")
        else deployment._run_deploy_receipts_after_merge(run_id=run_id, merge_result=result)
    )
    policy = {**policy, "deployment_receipt": receipt}
    if checkpoint is not None:
        checkpoint({"stage": "merge_observed", "policy": policy})
        production = receipt.get("production")
        if receipt.get("enabled") is True and not (
            receipt.get("ok") is True
            and receipt.get("staging_verified") is True
            and (
                receipt.get("production_enabled") is False
                or (isinstance(production, dict) and production.get("verified") is True)
            )
        ):
            raise RuntimeError("original_deployment_requires_reconciliation")
    return policy


def _recover_post_loop_policy(*, pending: dict, checkpoint: Callable[[dict], None]) -> dict:
    """Resume pure preflight, or read back an existing intent without another merge."""
    progress = pending.get("final_policy_progress") or {}
    policy = progress.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("gate") != pending.get("final_gate")
        or progress.get("binding")
        != {
            key: pending.get(key)
            for key in ("final_run_id", "user_id", "request_id", "code_task_id", "branch")
        }
    ):
        raise ValueError("original_final_policy_identity_mismatch")
    if progress.get("stage") == "before_policy":
        original = pending["final_record"]
        override = progress.get("policy_override")
        if override is not None:
            if (
                original.get("status") != "failed"
                or not isinstance(override, dict)
                or override.get("action") not in {"stop", "hold_for_automated_remediation"}
            ):
                raise ValueError("original_final_policy_override_mismatch")
            return override
        if not isinstance(policy.get("deployment_scope"), dict):
            raise ValueError("original_deployment_scope_unavailable")
        return _decide_post_loop_policy(
            branch=original["branch"],
            gate=pending["final_gate"],
            para_task_id=original["para_task_id"],
            run_id=original["run_id"],
            status=original["status"],
            steps=original["steps"],
            checkpoint=checkpoint,
            frozen_scope=policy["deployment_scope"],
        )
    if progress.get("stage") == "merge_intent":
        intent = progress.get("intent") or {}
        if any(
            intent.get(key) != value
            for key, value in {
                "run_id": pending.get("final_run_id"),
                "task_id": pending.get("code_task_id"),
                "branch": pending.get("branch"),
            }.items()
        ):
            raise ValueError("original_merge_intent_identity_mismatch")
        result = merge._readback_original_merge(intent)
        policy = {
            **policy,
            "action": "auto_merged_low_risk",
            "reason": "original_merge_verified_after_acknowledgement_loss",
            "merge_result": result,
        }
        checkpoint({"stage": "merge_observed", "policy": policy})
    elif progress.get("stage") != "merge_observed":
        raise ValueError("original_final_policy_receipt_unavailable")
    result = policy.get("merge_result") or {}
    expected = (
        "auto_merge_requested_low_risk" if result.get("merge_requested") else "auto_merged_low_risk"
    )
    if (
        result.get("ok") is not True
        or policy.get("action") != expected
        or (not result.get("merge_requested") and not result.get("merge_commit_sha"))
    ):
        raise ValueError("original_merge_receipt_unavailable")
    return _complete_merge_policy(pending["final_run_id"], policy, checkpoint=checkpoint)
