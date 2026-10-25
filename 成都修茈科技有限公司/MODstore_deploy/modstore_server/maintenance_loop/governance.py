"""Roster and governance audit gates required before automatic continuation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modstore_server import duty_employee_registry, duty_roster
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, store


def record_governance_audit_review(
    *, note: str = "", admin_user_id: Optional[Any] = None
) -> Dict[str, Any]:
    recent = store._read_governance_audit(10)
    summary = _governance_audit_summary(recent)
    record = {
        "action": "review_governance_audit",
        "admin_user_id": admin_user_id,
        "created_at": config._iso(config._utc_now()),
        "note": str(note or "")[:1000],
        "ok": True,
        "previous_summary": summary,
        "source": "self_maintenance_loop_api",
        "status": "reviewed",
    }
    path = store._append_governance_audit(record)
    next_recent = store._read_governance_audit(10)
    return {
        "ok": True,
        "audit_path": str(path),
        "record": record,
        "summary": _governance_audit_summary(next_recent),
    }


def _governance_audit_summary(
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    items = rows if isinstance(rows, list) else store._read_governance_audit(10)
    success_count = sum(
        (1 for item in items if isinstance(item, dict) and item.get("ok") is not False)
    )
    failure_count = sum((1 for item in items if isinstance(item, dict) and item.get("ok") is False))
    consecutive_failures = 0
    for item in reversed(items):
        if isinstance(item, dict) and item.get("ok") is False:
            consecutive_failures += 1
        else:
            break
    return {
        "recent_count": len(items),
        "success_count": success_count,
        "failure_count": failure_count,
        "consecutive_failures": consecutive_failures,
        "health": "bad" if consecutive_failures >= 2 else "warn" if failure_count else "ok",
    }


def _governance_audit_gate() -> Dict[str, Any]:
    summary = _governance_audit_summary()
    health = str(summary.get("health") or "").strip()
    ok = health != "bad"
    return {
        "ok": ok,
        "blocking": not ok,
        "action": "allow" if ok else "hold_for_governance_review",
        "reason": "governance_audit_healthy" if ok else "governance_audit_consecutive_failures",
        "summary": summary,
        "policy": "consecutive_governance_action_failures_pause_auto_continue_and_auto_merge",
    }


def _policy_active_gates_snapshot(
    *,
    evolution_metrics: Optional[Dict[str, Any]] = None,
    gate: Dict[str, Any],
    governance_gate: Dict[str, Any],
    report_only_missing: bool = False,
    roster_gate: Dict[str, Any],
    structured_gate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    evo = evolution_metrics if isinstance(evolution_metrics, dict) else {}
    structured = structured_gate if isinstance(structured_gate, dict) else {"ok": True}
    items = [
        {
            "key": "evidence",
            "label": "Evidence Gate",
            "status": "trigger" if gate.get("should_run") is True else "idle",
            "ok": True,
            "blocking": False,
            "reason": gate.get("reason") or gate.get("trigger_reason") or "",
            "detail": f"missing={gate.get('missing_count', 0)} threshold={gate.get('threshold', '')}",
        },
        {
            "key": "structured",
            "label": "Structured QA/Review",
            "status": "allow" if structured.get("ok") is not False else "blocked",
            "ok": structured.get("ok") is not False,
            "blocking": structured.get("ok") is False,
            "reason": structured.get("reason") or "",
            "detail": "QA/review JSON gate",
        },
        {
            "key": "report_only",
            "label": "Report-only Evidence",
            "status": "blocked" if report_only_missing else "allow",
            "ok": not report_only_missing,
            "blocking": bool(report_only_missing),
            "reason": "missing_report_only_evidence" if report_only_missing else "",
            "detail": "Para report-only evidence gate",
        },
        {
            "key": "roster",
            "label": "Roster Gate",
            "status": roster_gate.get("action") or "unknown",
            "ok": roster_gate.get("ok") is not False,
            "blocking": bool(roster_gate.get("blocking")),
            "reason": roster_gate.get("reason") or "",
            "detail": roster_gate.get("policy") or "",
        },
        {
            "key": "governance",
            "label": "Governance Gate",
            "status": governance_gate.get("action") or "unknown",
            "ok": governance_gate.get("ok") is not False,
            "blocking": bool(governance_gate.get("blocking")),
            "reason": governance_gate.get("reason") or "",
            "detail": governance_gate.get("policy") or "",
        },
        {
            "key": "evolution",
            "label": "Evolution Metrics",
            "status": "pause" if evo.get("pause") else "allow",
            "ok": not bool(evo.get("pause")),
            "blocking": bool(evo.get("pause")),
            "reason": evo.get("reason") or "",
            "detail": f"history={evo.get('history_count', 0)}",
        },
    ]
    blocking_items = [item for item in items if item.get("blocking")]
    return {
        "ok": not blocking_items,
        "blocking_count": len(blocking_items),
        "blocking_keys": [str(item.get("key") or "") for item in blocking_items],
        "items": items,
    }


def _loop_steps_roster_gate(
    steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    participant_ids: set[str] = set()

    def _collect(value: Any) -> None:
        if isinstance(value, dict):
            for key in (
                "employee_id",
                "employeeId",
                "emp_id",
                "empId",
                "actor",
                "assignee",
                "worker_id",
                "role_employee_id",
            ):
                text = str(value.get(key) or "").strip()
                if text:
                    participant_ids.add(text)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    _collect(child)
        elif isinstance(value, list):
            for item in value:
                _collect(item)

    _collect(steps)
    try:
        planned_ids = set(duty_roster.all_planned_employee_ids())
    except RECOVERABLE_ERRORS as exc:
        return {
            "action": "unknown",
            "blocking": True,
            "error": str(exc)[:300],
            "ok": False,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "duty_roster_load_error",
        }
    try:
        deployed_ids = set(duty_employee_registry.duty_employee_records().keys())
    except RECOVERABLE_ERRORS as exc:
        return {
            "action": "unknown",
            "blocking": True,
            "error": str(exc)[:300],
            "ok": False,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "duty_employee_registry_load_error",
        }
    in_roster_ids = sorted((emp_id for emp_id in participant_ids if emp_id in planned_ids))
    out_of_roster_ids = sorted((emp_id for emp_id in participant_ids if emp_id not in planned_ids))
    not_deployed_ids = sorted((emp_id for emp_id in in_roster_ids if emp_id not in deployed_ids))
    if out_of_roster_ids:
        return {
            "action": "isolate",
            "blocking": True,
            "in_roster_ids": in_roster_ids,
            "ok": False,
            "out_of_roster_ids": out_of_roster_ids,
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "out_of_roster_participants_detected",
        }
    if not_deployed_ids:
        return {
            "action": "hold",
            "blocking": True,
            "in_roster_ids": in_roster_ids,
            "not_deployed_ids": not_deployed_ids,
            "ok": False,
            "out_of_roster_ids": [],
            "participant_count": len(participant_ids),
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "in_roster_but_not_registered_duty_employee",
        }
    if not participant_ids:
        return {
            "action": "wait",
            "blocking": True,
            "in_roster_ids": [],
            "ok": False,
            "out_of_roster_ids": [],
            "participant_count": 0,
            "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
            "reason": "no_loop_participants_detected",
        }
    return {
        "action": "allow",
        "blocking": False,
        "in_roster_ids": in_roster_ids,
        "ok": True,
        "out_of_roster_ids": [],
        "participant_count": len(participant_ids),
        "policy": "only_registered_duty_roster_participants_can_pass_self_maintenance_policy",
        "reason": "all_participants_are_in_duty_roster",
    }
