"""Admin-facing approval execution contracts, summaries, and release reconciliation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.domain.autonomy.audit_log import append_autonomy_audit

from . import approval_resume as ledger


def _latest_actions() -> list[dict[str, Any]]:
    latest_by_id: dict[str, dict[str, Any]] = {}
    for item in ledger._read_ledger():
        action_id = str(item.get("action_id") or "")
        if action_id:
            latest_by_id[action_id] = item
    return list(latest_by_id.values())


def admin_execution_contract(item: dict[str, Any]) -> dict[str, Any]:
    """Describe whether the web approval center can execute a pending action."""

    action_id = str(item.get("action_id") or "")
    state = str(item.get("state") or "")
    executor_name = str(item.get("executor_name") or "")
    if state == "approval_requested":
        return {
            "admin_execution_ready": False,
            "execution_mode": "external_callback",
            "execution_guidance": "该动作已交给外部审批回调，请在对应审批提供方完成处理。",
        }
    if executor_name == "github_deploy":
        return {
            "admin_execution_ready": False,
            "execution_mode": "external_dispatch_required",
            "execution_guidance": "该发布必须由正式发布工作流审批并执行，管理端不能直接放行。",
        }
    if action_id in ledger._ACTION_EXECUTORS or executor_name in ledger._EXECUTORS:
        return {
            "admin_execution_ready": True,
            "execution_mode": "registered_executor",
            "execution_guidance": "通过后将立即调用已注册执行器并记录真实结果。",
        }
    return {
        "admin_execution_ready": False,
        "execution_mode": "executor_unavailable",
        "execution_guidance": "当前服务没有该动作的执行器，审批不会改变状态。",
    }


def reconcile_obsolete_release_actions(
    *,
    reference_action_id: str = "",
    resolved_by: str = "system:release-reconciler",
) -> list[dict[str, Any]]:
    """Append terminal rows for release approvals made obsolete by a real deploy."""

    actions = _latest_actions()
    if reference_action_id:
        reference = next(
            (
                item
                for item in actions
                if str(item.get("action_id") or "") == str(reference_action_id)
            ),
            None,
        )
    else:
        executed = [
            item
            for item in actions
            if str(item.get("action") or "") == "apply_release_to_cvm"
            and str(item.get("state") or "") == "executed"
        ]
        reference = max(
            executed,
            key=lambda item: str(item.get("timestamp") or ""),
            default=None,
        )
    if (
        reference is None
        or str(reference.get("action") or "") != "apply_release_to_cvm"
        or str(reference.get("state") or "") != "executed"
    ):
        return []

    reference_id = str(reference.get("action_id") or "")
    reference_timestamp = str(reference.get("timestamp") or "")
    actor = str(resolved_by or "system:release-reconciler").strip()
    candidates = sorted(
        (
            item
            for item in actions
            if str(item.get("action") or "") == "apply_release_to_cvm"
            and str(item.get("action_id") or "") != reference_id
            and str(item.get("state") or "") in {*ledger._AWAITING_REVIEW_STATES, "approved"}
            and str(item.get("timestamp") or "") <= reference_timestamp
        ),
        key=lambda item: str(item.get("timestamp") or ""),
    )
    reconciled: list[dict[str, Any]] = []
    for item in candidates:
        action_id = str(item.get("action_id") or "")
        ledger._ACTION_EXECUTORS.pop(action_id, None)
        row = ledger._append_ledger(
            {
                **item,
                "state": "superseded",
                "resolved_by": actor,
                "superseded_by": reference_id,
                "superseded_at": ledger._iso_now(),
                "supersession_reason": "a newer release reached the executed state",
            }
        )
        decision = item.get("risk_decision")
        risk_level = decision.get("risk_level") if isinstance(decision, dict) else "HIGH"
        append_autonomy_audit(
            {
                "action_id": action_id,
                "action": "apply_release_to_cvm",
                "risk_level": risk_level or "HIGH",
                "decision": "superseded",
                "approver": actor,
                "outcome": "will_not_retry",
                "event_type": "approval",
                "source": "approval_resume",
                "metadata": {"superseded_by": reference_id},
            }
        )
        reconciled.append(row)
    return reconciled


def list_pending_actions(*, limit: int = 100) -> list[dict[str, Any]]:
    pending = [
        {**item, **admin_execution_contract(item)}
        for item in _latest_actions()
        if item.get("state") in ledger._AWAITING_REVIEW_STATES
    ]
    return sorted(pending, key=lambda item: str(item.get("timestamp") or ""), reverse=True)[
        : max(1, min(int(limit), 1000))
    ]


def approval_center_snapshot(*, pending_limit: int = 100) -> dict[str, Any]:
    """Return one consistent approval-center snapshot from the append-only ledger."""

    latest = sorted(
        _latest_actions(),
        key=lambda item: str(item.get("timestamp") or ""),
        reverse=True,
    )
    pending = [
        {**item, **admin_execution_contract(item)}
        for item in latest
        if str(item.get("state") or "") in ledger._AWAITING_REVIEW_STATES
    ][: max(1, min(int(pending_limit), 1000))]
    execution_modes = Counter(str(item.get("execution_mode") or "unknown") for item in pending)
    states = Counter(str(item.get("state") or "unknown") for item in latest)
    return {
        "count": len(pending),
        "items": pending,
        "summary": {
            "states": dict(states),
            "execution_modes": dict(execution_modes),
            "actionable": sum(item.get("admin_execution_ready") is True for item in pending),
            "waiting": len(pending),
        },
    }


__all__ = [
    "admin_execution_contract",
    "approval_center_snapshot",
    "list_pending_actions",
    "reconcile_obsolete_release_actions",
]
