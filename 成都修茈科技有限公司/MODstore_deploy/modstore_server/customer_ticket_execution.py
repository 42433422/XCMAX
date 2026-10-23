"""Read-only, owner-bound progress projection for admins and scoped ticket readers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_

from modstore_server.customer_issue_delivery_contract import (
    execution_succeeded,
    role_progress_state,
    team_action_state,
)
from modstore_server.customer_service_tools import json_loads
from modstore_server.customer_ticket_reader import _reader_text
from modstore_server.models import IncidentEvent, User
from modstore_server.models_cs import CustomerServiceAction


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _current_claim(db, ticket, resolution):
    event_id = resolution.get("incident_event_id")
    events = (
        [db.get(IncidentEvent, event_id)]
        if isinstance(event_id, int) and event_id > 0
        else db.query(IncidentEvent)
        .filter(
            IncidentEvent.event_type == "ops.intake.customer_ticket",
            or_(
                IncidentEvent.payload_json.contains(f'"ticket_id":{ticket.id}'),
                IncidentEvent.payload_json.contains(f'"ticket_id": {ticket.id}'),
            ),
        )
        .order_by(IncidentEvent.id.desc())
        .limit(20)
    )
    for event in events:
        if event is None or event.event_type != "ops.intake.customer_ticket":
            continue
        payload = _object(json_loads(event.payload_json, {}))
        original = _object(payload.get("resolution"))
        if (
            payload.get("ticket_id") == ticket.id
            and payload.get("user_id") == ticket.user_id
            and original.get("reopened_at") == resolution.get("reopened_at")
            and resolution.get("incident_event_id") in (None, event.id)
        ):
            return event.id, _object(payload.get("_team_claim"))
    return None, {}


def _receipts(claim: dict) -> list[dict]:
    rows = _rows(claim.get("team"))
    receipts = []
    for row in rows:
        for output in _rows(_object(row.get("handler_outputs")).get("outputs")):
            if output.get("handler") != "para_delegate":
                continue
            task_id = output.get("task_id") or output.get("para_task_id")
            receipts.append(
                {
                    "kind": "execution",
                    "role": row.get("role"),
                    "employee_id": row.get("employee_id"),
                    "state": row.get("status"),
                    "task_id": task_id,
                    "accepted": output.get("accepted") is True and bool(task_id),
                    "completed": execution_succeeded(output),
                    "requires_reconciliation": output.get("requires_reconciliation") is True,
                    "updated_at": output.get("updated_at"),
                }
            )
    attempts = {row.get("role"): row.get("attempt_id") for row in rows}
    for receipt in _object(claim.get("escalations")).values():
        if (
            not isinstance(receipt, dict)
            or not receipt.get("attempt_id")
            or (receipt.get("attempt_id") != attempts.get(receipt.get("role")))
        ):
            continue
        task_id, state = receipt.get("task_id"), receipt.get("state")
        receipts.append(
            {
                "kind": "escalation",
                "role": receipt.get("role"),
                "employee_id": receipt.get("target_tool"),
                "state": state,
                "task_id": task_id,
                "accepted": state in {"accepted", "completed"}
                and receipt.get("accepted") is True
                and bool(task_id),
                "completed": state == "completed" and receipt.get("completed") is True,
                "requires_reconciliation": receipt.get("requires_reconciliation") is True,
                "updated_at": receipt.get("updated_at"),
            }
        )
    return [
        {
            key: value if isinstance(value, bool) or value is None else _reader_text(value, 160)
            for key, value in receipt.items()
        }
        for receipt in receipts
    ]


def _work_order(db, ticket, evidence):
    from modstore_server.work_order_api import _customer_view

    wo_id = str(evidence.get("work_order_id") or "")
    if not wo_id:
        return {"binding": "not_linked", "id": None, "status": None}
    owner = db.get(User, ticket.user_id)
    view = _customer_view(db, wo_id, owner) if owner else None
    return (
        {"binding": "verified", "id": wo_id, "status": view["status"]}
        if view
        else {"binding": "unavailable", "id": None, "status": None}
    )


def _next_step(ticket, resolution, rows, receipts, *, claim_verified=False):
    if ticket.status in {"resolved", "closed", "expired"}:
        return "none", "原单已结束；如问题复现，由客户从原单重开", "none"
    if any(
        row.get("requires_reconciliation") or row.get("state") in {"unknown", "dispatching"}
        for row in receipts
    ):
        return "reconcile_task", "查询已有任务回执，确认结果后继续", "task_receipt"
    if any(
        row.get("kind") == "escalation" and row.get("accepted") and not row.get("completed")
        for row in receipts
    ):
        return "await_review", "跟进已受理的复核任务，并核对执行结果", "review_in_progress"
    if resolution.get("state") == "awaiting_customer_verification":
        return (
            "customer_confirmation",
            "请原客户在适用版本复测并从原单确认或重开",
            "customer_confirmation",
        )
    if resolution.get("repair_verified") is True:
        return "deliver_repair", "核验包含本单修复的正式发布并绑定客户目标", "release_binding"
    current_waiting = (
        claim_verified
        and len(rows) == 3
        and {row.get("role") for row in rows} == {"scout", "fix", "verify"}
        and team_action_state(rows)[0] == "pending"
    )
    failed = next(
        (row for row in rows if role_progress_state(row) in {"failed", "manual_review"}),
        None,
    )
    if failed or (
        not current_waiting
        and resolution.get("state")
        in {"repair_failed", "awaiting_manual_review", "dispatch_failed"}
    ):
        return "review_failure", "核对失败环节及接手回执，按已有恢复流程继续", "execution_failed"
    if rows:
        return "follow_execution", "跟进当前环节；前序完成后继续后续环节", "execution_pending"
    return "confirm_assignment", "核对派单记录并确认实际执行接单", "assignment_unconfirmed"


def _last_progress(resolution, actions, receipts):
    candidates = [(resolution.get("updated_at"), "处理结论更新")]
    candidates += [(action.created_at, "原单动作记录") for action in actions]
    candidates += [
        (row.get("updated_at"), "复核任务回执更新")
        for row in receipts
        if row.get("kind") == "escalation"
    ]
    parsed = []
    for value, label in candidates:
        try:
            at = (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            )
            at = at.replace(tzinfo=UTC) if at.tzinfo is None else at
            parsed.append((at, label))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return {"at": None, "label": "尚无执行进展记录"}
    at, label = max(parsed, key=lambda item: item[0])
    return {"at": at.isoformat(), "label": label}


def ticket_execution_overview(db, ticket) -> dict:
    """Derive status from current evidence without writing another lifecycle ledger."""
    evidence = _object(json_loads(ticket.evidence_json, {}))
    resolution = _object(evidence.get("resolution"))
    event_id, claim = _current_claim(db, ticket, resolution)
    claim_rows = _rows(claim.get("team"))
    rows = claim_rows or _rows(resolution.get("team"))
    receipts = _receipts(claim)
    actions = (
        db.query(CustomerServiceAction)
        .filter_by(ticket_id=ticket.id, user_id=ticket.user_id)
        .order_by(CustomerServiceAction.id.desc())
        .limit(30)
        .all()
    )
    code, label, blocker = _next_step(
        ticket, resolution, rows, receipts, claim_verified=event_id is not None and bool(claim_rows)
    )
    current = next((row for row in rows if row.get("ok") is not True), {})
    assignee = db.get(User, ticket.assigned_admin_id) if ticket.assigned_admin_id else None
    accepted_review = next(
        (
            r
            for r in receipts
            if r.get("kind") == "escalation" and r.get("accepted") and not r.get("completed")
        ),
        {},
    )
    if code == "none":
        responsible = {"kind": "none", "label": "无当前待办", "id": None}
    elif code == "customer_confirmation":
        responsible = {"kind": "customer", "label": "原工单客户", "id": ticket.user_id}
    elif accepted_review:
        responsible = {"kind": "reviewer", "label": accepted_review["employee_id"], "id": None}
    elif current.get("employee_id"):
        responsible = {
            "kind": "employee",
            "label": _reader_text(current["employee_id"]),
            "role": _reader_text(current.get("role") or ""),
            "id": None,
        }
    elif assignee:
        responsible = {"kind": "admin", "label": _reader_text(assignee.username), "id": assignee.id}
    else:
        responsible = {"kind": "unassigned", "label": "暂无当前责任人记录", "id": None}
    return {
        "customer_ticket": {"id": ticket.id, "status": ticket.status},
        "work_order": _work_order(db, ticket, evidence),
        "incident_event_id": event_id,
        "blocker": blocker,
        "responsible": responsible,
        "receipts": receipts,
        "last_progress": _last_progress(resolution, actions, receipts),
        "next_step": {"code": code, "label": label},
        "verification": {
            "repair_verified": resolution.get("repair_verified") is True,
            "source": _reader_text(resolution.get("repair_verified_by") or ""),
            "release_bound": bool(_object(resolution.get("release_target"))),
            "customer_confirmed": resolution.get("verification_mode")
            in {"customer_decision", "customer_confirmation"}
            and ticket.status == "resolved",
        },
    }
