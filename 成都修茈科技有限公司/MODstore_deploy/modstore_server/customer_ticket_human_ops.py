# mypy: disable-error-code="arg-type, assignment"
"""Human assign / accept / diagnose / approve / verify for one customer ticket.

Automatic employee dispatch must not move an unassigned ticket to processing.
Every transition records the operator, time, reason, and the status before and after.
The ticket row lives in the market database table customer_service_tickets.
The desktop and the admin console only proxy that row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.customer_issue_delivery_contract import issue_resolution, repair_verification
from modstore_server.customer_service_tools import (
    audit,
    begin_immediate_write,
    build_action,
    execute_action,
    json_dumps,
    json_loads,
)
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceTicket


def _evidence(ticket: CustomerServiceTicket) -> dict[str, Any]:
    evidence = json_loads(ticket.evidence_json, {})
    return evidence if isinstance(evidence, dict) else {}


def _cas(
    db: Session,
    ticket: CustomerServiceTicket,
    user: User,
    *,
    expected: str,
    new_status: str,
    event: str,
    reason: str,
    evidence: dict[str, Any],
    assignee: int | None = None,
    set_assignee: bool = False,
) -> CustomerServiceTicket:
    begin_immediate_write(db)
    before = str(ticket.status or "")
    if before != expected:
        raise HTTPException(409, f"工单当前是{before}，不能执行{event}")
    expected_version = int(getattr(ticket, "lock_version", 0) or 0)
    now = datetime.now(UTC)
    history = [row for row in evidence.get("handling_history") or [] if isinstance(row, dict)]
    history.append(
        {
            "at": now.isoformat(),
            "operator_id": int(user.id),
            "operator": str(getattr(user, "username", "") or ""),
            "action": event,
            "reason": reason[:2000],
            "before_status": before,
            "after_status": new_status,
            "assigned_admin_id": assignee if set_assignee else ticket.assigned_admin_id,
        }
    )
    evidence["handling_history"] = history[-80:]
    values: dict[str, Any] = {
        "status": new_status,
        "updated_at": now,
        "evidence_json": json_dumps(evidence),
        "lock_version": expected_version + 1,
    }
    if set_assignee:
        values["assigned_admin_id"] = assignee
    changed = (
        db.query(CustomerServiceTicket)
        .filter(
            CustomerServiceTicket.id == ticket.id,
            CustomerServiceTicket.status == expected,
            CustomerServiceTicket.lock_version == expected_version,
        )
        .update(values, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "工单状态已被其他人更新，请刷新后重试")
    db.refresh(ticket)
    audit(
        db,
        event_type=event,
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        actor=user,
        actor_type="admin",
        detail={
            "reason": reason[:2000],
            "before_status": before,
            "after_status": new_status,
            "assigned_admin_id": ticket.assigned_admin_id,
            "at": now.isoformat(),
        },
    )
    db.commit()
    db.refresh(ticket)
    return ticket


def assign_ticket(
    db: Session, ticket: CustomerServiceTicket, user: User, assignee_id: int, reason: str
) -> CustomerServiceTicket:
    if ticket.status not in {"open", "processing", "awaiting_customer"}:
        raise HTTPException(409, "当前状态不能指派")
    assignee = db.get(User, int(assignee_id))
    if assignee is None or not assignee.is_admin:
        raise HTTPException(422, "只能指派给在职技术管理员")
    evidence = _evidence(ticket)
    assignments = [row for row in evidence.get("assignment_history") or [] if isinstance(row, dict)]
    now = datetime.now(UTC)
    assignments.append(
        {
            "at": now.isoformat(),
            "by_user_id": int(user.id),
            "by_username": str(getattr(user, "username", "") or ""),
            "assignee_id": int(assignee.id),
            "assignee_username": str(assignee.username or ""),
            "previous_assignee_id": ticket.assigned_admin_id,
            "reason": reason[:2000],
        }
    )
    evidence["assignment_history"] = assignments[-40:]
    # Reassignment returns the ticket to open so the previous handler loses accept rights.
    return _cas(
        db,
        ticket,
        user,
        expected=str(ticket.status),
        new_status="open",
        event="ticket_assigned",
        reason=reason,
        evidence=evidence,
        assignee=int(assignee.id),
        set_assignee=True,
    )


def accept_ticket(
    db: Session, ticket: CustomerServiceTicket, user: User, reason: str
) -> CustomerServiceTicket:
    if ticket.assigned_admin_id != int(user.id):
        raise HTTPException(403, "只有当前被指派的处理人可以受理")
    if ticket.status != "open":
        raise HTTPException(409, "只有待受理工单可以开始处理")
    return _cas(
        db,
        ticket,
        user,
        expected="open",
        new_status="processing",
        event="ticket_accepted",
        reason=reason,
        evidence=_evidence(ticket),
    )


def record_diagnosis(
    db: Session, ticket: CustomerServiceTicket, user: User, text: str
) -> CustomerServiceTicket:
    if ticket.assigned_admin_id != int(user.id) or ticket.status != "processing":
        raise HTTPException(403, "只有处理中的当前处理人可以记录诊断")
    evidence = _evidence(ticket)
    notes = [row for row in evidence.get("diagnoses") or [] if isinstance(row, dict)]
    now = datetime.now(UTC)
    notes.append(
        {
            "at": now.isoformat(),
            "operator_id": int(user.id),
            "operator": str(getattr(user, "username", "") or ""),
            "text": text[:4000],
        }
    )
    evidence["diagnoses"] = notes[-40:]
    evidence["fault_remains"] = True
    return _cas(
        db,
        ticket,
        user,
        expected="processing",
        new_status="processing",
        event="ticket_diagnosed",
        reason=text,
        evidence=evidence,
    )


def request_sensitive_action(
    db: Session, ticket: CustomerServiceTicket, user: User, change: str, reason: str
) -> dict[str, Any]:
    if ticket.assigned_admin_id != int(user.id) or ticket.status != "processing":
        raise HTTPException(403, "只有处理中的当前处理人可以申请敏感操作")
    action = build_action(
        db,
        ticket_id=int(ticket.id),
        user_id=int(user.id),
        action_type="ticket.apply_change",
        target_type="ticket",
        target_id="gated",
        request={
            "change": change[:200],
            "reason": reason[:2000],
            "operator_id": int(user.id),
            "ticket_status": str(ticket.status or ""),
            "ticket_lock_version": int(getattr(ticket, "lock_version", 0) or 0),
        },
    )
    execute_action(db, action, user)
    audit(
        db,
        event_type="sensitive_action_requested",
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        actor=user,
        actor_type="admin",
        detail={"action_id": action.id, "status": action.status, "change": change[:200]},
    )
    db.commit()
    return {
        "action_id": action.id,
        "status": action.status,
        "executed": action.status == "completed",
    }


def decide_sensitive_action(
    db: Session,
    ticket: CustomerServiceTicket,
    user: User,
    action_id: int,
    *,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    from modstore_server.models_cs import CustomerServiceAction

    begin_immediate_write(db)
    locked = (
        db.query(CustomerServiceTicket)
        .filter(CustomerServiceTicket.id == int(ticket.id))
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise HTTPException(404, "没有这张工单")
    ticket = locked
    action = (
        db.query(CustomerServiceAction)
        .filter_by(id=int(action_id), ticket_id=ticket.id, action_type="ticket.apply_change")
        .populate_existing()
        .with_for_update()
        .first()
    )
    if action is None:
        raise HTTPException(404, "没有这张敏感操作申请")
    request = json_loads(action.request_json, {})
    if not isinstance(request, dict):
        request = {}
    if (
        str(action.status or "") == "rejected"
        or str(action.error or "") == "approval_rejected"
        or str((request.get("approval") or {}).get("decision") or "") == "rejected"
        or request.get("consumed_approval_id")
    ):
        if (
            str((request.get("approval") or {}).get("decision") or "") == "rejected"
            or str(action.error or "") == "approval_rejected"
        ):
            action.status = "rejected"
            action.error = "approval_rejected"
        db.commit()
        raise HTTPException(409, "这张审批已经处理过，不能再次决定")
    if str(action.status or "") != "waiting_approval":
        raise HTTPException(409, "只有等待审批的操作可以批准或拒绝")
    if int(user.id) == int(action.user_id or 0):
        raise HTTPException(403, "申请人不能审批自己的敏感操作")
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "审批决定无效")
    bound_status = str(request.get("ticket_status") or "")
    if bound_status and bound_status != str(ticket.status or ""):
        raise HTTPException(409, "工单状态已变化，这次审批已经失效")
    request["approval"] = {
        "id": f"human-{action.id}-{decision}",
        "decision": decision,
        "approver_id": int(user.id),
        "reason": reason[:2000],
        "ticket_status": str(ticket.status or ""),
        "at": datetime.now(UTC).isoformat(),
    }
    action.request_json = json_dumps(request)
    from modstore_server.customer_service_tools import claim_gated_decision

    claim_gated_decision(db, action, user, request)
    audit(
        db,
        event_type="sensitive_action_decided",
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        actor=user,
        actor_type="admin",
        detail={
            "action_id": action.id,
            "decision": decision,
            "status": action.status,
            "reason": reason[:2000],
            "executed": action.status == "completed",
        },
    )
    db.commit()
    return {
        "action_id": action.id,
        "status": action.status,
        "executed": action.status == "completed",
        "approval": request["approval"],
    }


def submit_result(
    db: Session,
    ticket: CustomerServiceTicket,
    user: User,
    *,
    text: str,
    fault_remains: bool,
) -> CustomerServiceTicket:
    if ticket.status != "processing":
        raise HTTPException(403, "只有处理中的工单可以提交结果")
    evidence = _evidence(ticket)
    diagnoses = [row for row in evidence.get("diagnoses") or [] if isinstance(row, dict)]
    if not diagnoses:
        raise HTTPException(409, "还没有诊断记录，不能提交结果")
    diagnoser = int(diagnoses[-1].get("operator_id") or 0)
    if fault_remains:
        if ticket.assigned_admin_id != int(user.id):
            raise HTTPException(403, "只有当前处理人可以记录故障仍在")
    elif int(user.id) in {diagnoser, int(ticket.assigned_admin_id or 0)}:
        raise HTTPException(403, "复测必须由另一位管理员独立确认")
    evidence["fault_remains"] = bool(fault_remains)
    evidence["handling_result"] = {
        "at": datetime.now(UTC).isoformat(),
        "operator_id": int(user.id),
        "text": text[:4000],
        "fault_remains": bool(fault_remains),
    }
    resolution = issue_resolution(ticket, evidence)
    if fault_remains:
        resolution.update(state="processing", **repair_verification(None))
        evidence["resolution"] = resolution
        return _cas(
            db,
            ticket,
            user,
            expected="processing",
            new_status="processing",
            event="ticket_result_fault_remains",
            reason=text,
            evidence=evidence,
        )
    resolution.update(state="awaiting_customer_verification", **repair_verification("human_retest"))
    evidence["resolution"] = resolution
    return _cas(
        db,
        ticket,
        user,
        expected="processing",
        new_status="awaiting_customer",
        event="ticket_result_ready",
        reason=text,
        evidence=evidence,
    )
