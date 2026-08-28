"""Persistent pending-approval ledger and audited resume/reject state machine."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.domain.autonomy.audit_log import append_autonomy_audit
from app.domain.autonomy.autonomy_guard import RiskDecision, evaluate_risk
from app.utils.operational_errors import RECOVERABLE_ERRORS

_FHD_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LEDGER_PATH = _FHD_ROOT / "metrics" / "autonomy-approval-ledger.jsonl"
_LOCK = threading.RLock()
UTC = timezone.utc  # noqa: UP017 - shared module must import on Python 3.10
_EXECUTORS: dict[str, Callable[[dict[str, Any]], Any]] = {}
_ACTION_EXECUTORS: dict[str, Callable[[dict[str, Any]], Any]] = {}
_TERMINAL_STATES = frozenset({"executed", "rejected", "execution_failed", "superseded"})
_AWAITING_REVIEW_STATES = frozenset({"pending_approval", "approval_requested"})
_SENSITIVE_KEYS = frozenset({"token", "secret", "password", "authorization", "api_key"})


class ApprovalStateError(RuntimeError):
    pass


class ExecutionNotDispatchableError(ApprovalStateError):
    """The approval exists, but this control plane cannot execute it safely."""


def _ledger_path() -> Path:
    raw = (os.environ.get("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    data_root = (os.environ.get("XCAGI_AUTONOMY_DATA_DIR") or "").strip()
    if data_root:
        return Path(data_root).expanduser() / _DEFAULT_LEDGER_PATH.name
    xcagi_root = (os.environ.get("XCAGI_DATA_DIR") or "").strip()
    if xcagi_root:
        return Path(xcagi_root).expanduser() / "autonomy" / _DEFAULT_LEDGER_PATH.name
    return _DEFAULT_LEDGER_PATH


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if any(mark in str(key).lower() for mark in _SENSITIVE_KEYS)
            else _safe_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _append_ledger(record: dict[str, Any]) -> dict[str, Any]:
    row = {**record, "timestamp": str(record.get("timestamp") or _iso_now())}
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def _read_ledger() -> list[dict[str, Any]]:
    path = _ledger_path()
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    with _LOCK, path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                result.append(item)
    return result


def _latest(action_id: str) -> dict[str, Any] | None:
    for item in reversed(_read_ledger()):
        if str(item.get("action_id") or "") == str(action_id):
            return item
    return None


def get_action_state(action_id: str) -> dict[str, Any] | None:
    latest = _latest(action_id)
    return dict(latest) if latest is not None else None


def register_action_executor(
    name: str,
    executor: Callable[[dict[str, Any]], Any],
    *,
    action_id: str | None = None,
) -> None:
    if action_id:
        _ACTION_EXECUTORS[str(action_id)] = executor
    else:
        _EXECUTORS[str(name)] = executor


def record_pending_action(
    *,
    action: str,
    action_id: str,
    payload: dict[str, Any] | None,
    decision: RiskDecision,
    source: str,
    executor_name: str = "",
    executor: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if not decision.requires_confirmation or decision.allowed:
        raise ApprovalStateError("only a pending RiskDecision can enter pending_approval")
    existing = _latest(action_id)
    if existing and str(existing.get("action") or "") != action:
        raise ApprovalStateError(
            f"action_id {action_id} already belongs to {existing.get('action')}"
        )
    if existing and str(existing.get("state") or "") in _AWAITING_REVIEW_STATES:
        return existing
    if existing and str(existing.get("state") or "") in _TERMINAL_STATES:
        # Idempotent scheduler retries must not resurrect rejected/finished work.
        return existing
    if existing and str(existing.get("state") or "") == "approved":
        # A deferred executor owns this action now. Scheduler retries must not
        # turn it back into a pending approval.
        return existing
    if executor is not None:
        register_action_executor(action, executor, action_id=action_id)
    row = _append_ledger(
        {
            "action_id": action_id,
            "action": action,
            "state": "pending_approval",
            "source": source,
            "executor_name": executor_name,
            "payload": _safe_payload(payload or {}),
            "risk_decision": decision.to_dict(),
        }
    )
    append_autonomy_audit(
        {
            "action_id": action_id,
            "action": action,
            "risk_level": decision.risk_level.name,
            "decision": "pending_approval",
            "outcome": "queued",
            "event_type": "approval",
            "policy": decision.policy,
            "rollback_path": decision.rollback_path,
            "source": source,
        }
    )
    return row


def mark_approval_requested(
    action_id: str,
    *,
    approval_id: str,
    source: str = "github_dispatcher",
) -> dict[str, Any]:
    latest = _latest(action_id)
    if latest is None:
        raise ApprovalStateError(f"pending action not found: {action_id}")
    state = str(latest.get("state") or "")
    if state == "approval_requested":
        return latest
    if state != "pending_approval":
        raise ApprovalStateError(f"action {action_id} is not pending (state={state})")
    row = _append_ledger(
        {
            **latest,
            "state": "approval_requested",
            "approval_id": str(approval_id or ""),
            "approval_requested_at": _iso_now(),
        }
    )
    risk = (latest.get("risk_decision") or {}).get("risk_level") or "BLOCKED"
    append_autonomy_audit(
        {
            "action_id": action_id,
            "action": str(latest.get("action") or ""),
            "risk_level": risk,
            "decision": "approval_requested",
            "outcome": "github_environment_requested",
            "event_type": "approval",
            "source": source,
            "metadata": {"approval_id": str(approval_id or "")},
        }
    )
    return row


def request_action(
    action: str,
    *,
    payload: dict[str, Any] | None = None,
    action_id: str | None = None,
    source: str = "runtime",
    executor_name: str = "",
    executor: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[RiskDecision, dict[str, Any] | None]:
    resolved_id = str(action_id or uuid.uuid4().hex)
    decision = evaluate_risk(action, action_id=resolved_id, source=source)
    pending = None
    if decision.requires_confirmation and not decision.allowed:
        pending = record_pending_action(
            action=action,
            action_id=resolved_id,
            payload=payload,
            decision=decision,
            source=source,
            executor_name=executor_name,
            executor=executor,
        )
    return decision, pending


def _execute_self_maintenance_merge(payload: dict[str, Any]) -> Any:
    from modstore_server.self_maintenance_loop_runner import _auto_merge_low_risk_branch

    approval = payload.get("_approval") if isinstance(payload.get("_approval"), dict) else {}
    if not isinstance(approval, dict):
        approval = {}
    return _auto_merge_low_risk_branch(
        run_id=str(payload.get("run_id") or ""),
        task_id=str(payload.get("task_id") or "") or None,
        branch=str(payload.get("branch") or "") or None,
        steps=payload.get("steps") if isinstance(payload.get("steps"), list) else None,
        human_approved=True,
        approved_by=str(approval.get("approver") or "github-environment"),
    )


register_action_executor("self_maintenance_merge", _execute_self_maintenance_merge)


def resume_action(
    action_id: str,
    *,
    approver: str,
    approval_id: str = "",
    executor: Callable[[dict[str, Any]], Any] | None = None,
    defer_execution: bool = False,
) -> dict[str, Any]:
    latest = _latest(action_id)
    if latest is None:
        raise ApprovalStateError(f"pending action not found: {action_id}")
    state = str(latest.get("state") or "")
    if state == "rejected":
        raise ApprovalStateError(f"action {action_id} was rejected and cannot be retried")
    if state not in _AWAITING_REVIEW_STATES:
        raise ApprovalStateError(f"action {action_id} is not pending (state={state})")
    actor = str(approver or "").strip()
    if not actor:
        raise ApprovalStateError("approver is required")
    action = str(latest.get("action") or "")
    payload = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
    decision = evaluate_risk(
        action,
        {
            "human_approved": True,
            "approved_by": actor,
            "approval_id": approval_id,
            "trigger": "approval_resume",
        },
        action_id=action_id,
        source="approval_resume",
    )
    if not decision.allowed:
        raise ApprovalStateError(f"autonomy_guard still denied action: {decision.reason}")
    chosen: Callable[[dict[str, Any]], Any] | None = None
    if not defer_execution:
        chosen = executor or _ACTION_EXECUTORS.pop(action_id, None)
        if chosen is None:
            chosen = _EXECUTORS.get(str(latest.get("executor_name") or ""))
        if chosen is None:
            raise ExecutionNotDispatchableError(
                f"approved action {action_id} has no registered executor; execution was not attempted"
            )
    approved_row = _append_ledger(
        {
            **latest,
            "state": "approved",
            "approver": actor,
            "approval_id": approval_id,
            "approved_at": _iso_now(),
        }
    )
    append_autonomy_audit(
        {
            "action_id": action_id,
            "action": action,
            "risk_level": decision.risk_level.name,
            "decision": "approved",
            "approver": actor,
            "outcome": "execution_deferred" if defer_execution else "execution_started",
            "event_type": "approval",
            "policy": decision.policy,
            "rollback_path": decision.rollback_path,
            "source": "approval_resume",
            "metadata": {"approval_id": approval_id},
        }
    )
    if defer_execution:
        return approved_row
    assert chosen is not None
    try:
        raw_outcome = chosen(
            {
                **dict(payload or {}),
                "_approval": {"approver": actor, "approval_id": approval_id},
            }
        )
        outcome = raw_outcome if isinstance(raw_outcome, dict) else {"result": raw_outcome}
        ok = bool(outcome.get("ok", outcome.get("success", True)))
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - executor boundary must become an audited outcome
        outcome = {"ok": False, "error": str(exc)}
        ok = False
    return complete_action(
        action_id,
        success=ok,
        approver=actor,
        approval_id=approval_id,
        outcome=outcome,
    )


def complete_action(
    action_id: str,
    *,
    success: bool,
    approver: str = "",
    approval_id: str = "",
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record the real executor result after a deferred workflow action."""

    latest = _latest(action_id)
    if latest is None:
        raise ApprovalStateError(f"approved action not found: {action_id}")
    state = str(latest.get("state") or "")
    terminal_state = "executed" if success else "execution_failed"
    if state == terminal_state:
        # The server-side deploy script and the authenticated workflow callback
        # both report the same real outcome. Treat the second report as an
        # idempotent acknowledgement instead of failing a successful workflow.
        return latest
    if state in _TERMINAL_STATES:
        raise ApprovalStateError(f"action {action_id} is already terminal (state={state})")
    if state != "approved":
        raise ApprovalStateError(f"action {action_id} is not approved (state={state})")
    actor = str(approver or latest.get("approver") or "").strip()
    if not actor:
        raise ApprovalStateError("approver is required")
    safe_outcome = _safe_payload(outcome or {})
    terminal_at_key = "executed_at" if success else "execution_failed_at"
    row = _append_ledger(
        {
            **latest,
            "state": terminal_state,
            "approver": actor,
            "approval_id": approval_id or str(latest.get("approval_id") or ""),
            "outcome": safe_outcome,
            terminal_at_key: _iso_now(),
        }
    )
    risk = (latest.get("risk_decision") or {}).get("risk_level") or "BLOCKED"
    append_autonomy_audit(
        {
            "action_id": action_id,
            "action": str(latest.get("action") or ""),
            "risk_level": risk,
            "decision": terminal_state,
            "approver": actor,
            "outcome": terminal_state,
            "event_type": "action_outcome",
            "source": "approval_resume",
            "metadata": {
                "approval_id": approval_id or str(latest.get("approval_id") or ""),
                "outcome": safe_outcome,
            },
        }
    )
    if success and str(latest.get("action") or "") == "apply_release_to_cvm":
        from app.application.autonomy.approval_center import (
            reconcile_obsolete_release_actions,
        )

        superseded = reconcile_obsolete_release_actions(
            reference_action_id=action_id,
            resolved_by="system:release-reconciler",
        )
        if superseded:
            row = {**row, "superseded_count": len(superseded)}
    return row


def reject_action(
    action_id: str,
    *,
    approver: str,
    reason: str = "",
    approval_id: str = "",
) -> dict[str, Any]:
    latest = _latest(action_id)
    if latest is None:
        raise ApprovalStateError(f"pending action not found: {action_id}")
    if str(latest.get("state") or "") not in _AWAITING_REVIEW_STATES:
        raise ApprovalStateError(f"action {action_id} is not pending")
    actor = str(approver or "").strip()
    if not actor:
        raise ApprovalStateError("approver is required")
    _ACTION_EXECUTORS.pop(action_id, None)
    row = _append_ledger(
        {
            **latest,
            "state": "rejected",
            "approver": actor,
            "approval_id": approval_id,
            "rejection_reason": str(reason or "")[:1000],
            "rejected_at": _iso_now(),
        }
    )
    risk = (latest.get("risk_decision") or {}).get("risk_level") or "BLOCKED"
    append_autonomy_audit(
        {
            "action_id": action_id,
            "action": str(latest.get("action") or ""),
            "risk_level": risk,
            "decision": "rejected",
            "approver": actor,
            "outcome": "will_not_retry",
            "event_type": "approval",
            "source": "approval_resume",
            "metadata": {"approval_id": approval_id, "reason": str(reason or "")[:1000]},
        }
    )
    return row


__all__ = [
    "ApprovalStateError",
    "ExecutionNotDispatchableError",
    "complete_action",
    "get_action_state",
    "mark_approval_requested",
    "record_pending_action",
    "register_action_executor",
    "reject_action",
    "request_action",
    "resume_action",
]
