"""Read delivery facts and notify opted-in admins about material changes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from modstore_server.customer_delivery_receipts import all_artifacts_running
from modstore_server.customer_service_delivery_models import (
    current_delivery_run,
    custom_delivery_evidence,
    delivery_snapshot_matches,
)
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import Notification, User, get_session_factory
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceTicket,
    XiaoCDeliveryFollowup,
)

_TICKET = CustomerServiceTicket
_WATCH = XiaoCDeliveryFollowup
_CLOSED = {"resolved", "closed", "done", "cancelled"}
_AUDIT_LABELS = {
    "ticket_assigned": "已指派处理人",
    "ticket_accepted": "处理人已受理",
    "ticket_diagnosed": "处理人已记录诊断",
    "expected_completion_updated": "预计完成时间已更新",
    "ticket_loop_timeout": "工单任务超时",
    "custom_delivery_internal_approved": "内部审核已通过，待客户验收",
    "custom_delivery_accepted": "客户已验收",
    "custom_delivery_rework_requested": "已发起返工",
    "sensitive_action_requested": "已提交敏感操作审批",
    "sensitive_action_decided": "已记录审批决定",
}
_RECEIPT_LABELS = {
    "installed": "收到安装回执",
    "running": "收到运行回执",
    "verification_failed": "收到业务验证失败回执",
}
_ACTION_LABELS = {
    "ticket.assign": "派单",
    "ticket.read": "读取工单",
    "ticket.observe_status": "核对工单状态",
    "ticket.diagnose": "诊断问题",
    "ticket.report_diagnosis": "记录诊断",
    "ticket.verify": "核验处理结果",
    "ticket.apply_change": "申请敏感变更",
}


def utc_time(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value: object) -> str | None:
    normalized = utc_time(value)
    return normalized.isoformat() if normalized else None


def owns_delivery(ticket: _TICKET, user_id: int) -> bool:
    return user_id in (ticket.user_id, ticket.assigned_admin_id)


def scoped_deliveries(db: Session, user_id: int, *, include_reviews: bool = False):
    scope = or_(_TICKET.user_id == user_id, _TICKET.assigned_admin_id == user_id)
    if include_reviews:
        # The human review route authorizes independent admins for a pending request only.
        scope = or_(
            scope,
            exists().where(
                CustomerServiceAction.ticket_id == _TICKET.id,
                CustomerServiceAction.action_type == "ticket.apply_change",
                CustomerServiceAction.status == "waiting_approval",
                CustomerServiceAction.user_id != user_id,
                _TICKET.status.not_in(_CLOSED),
                _TICKET.closed_at.is_(None),
            ),
        )
    return db.query(_TICKET).filter(
        _TICKET.intent == "custom_delivery",
        scope,
    )


def is_closed(ticket: _TICKET) -> bool:
    return ticket.status in _CLOSED or bool(ticket.closed_at)


def is_delivered(ticket: _TICKET, evidence: dict[str, Any]) -> bool:
    resolution = evidence.get("resolution")
    return (
        str(ticket.status) == "resolved"
        and bool(evidence.get("delivered_at"))
        and isinstance(resolution, dict)
        and resolution.get("repair_verified_by") == "delivery_runtime_receipt"
        and all_artifacts_running(ticket, evidence)
    )


def pending_change(db: Session, ticket: _TICKET, user_id: int) -> dict[str, str] | None:
    """Expose the exact requested change only when another authorized admin can review it."""
    if is_closed(ticket):
        return None
    action = (
        db.query(CustomerServiceAction)
        .filter_by(
            ticket_id=ticket.id,
            action_type="ticket.apply_change",
            status="waiting_approval",
        )
        .order_by(CustomerServiceAction.id.desc())
        .first()
    )
    if action is None or action.user_id == user_id:
        return None
    request = json_loads(cast(str | None, action.request_json), {})
    if (
        not isinstance(request, dict)
        or request.get("consumed_approval_id")
        or request.get("ticket_status", ticket.status) != ticket.status
    ):
        return None
    change, reason = request.get("change"), request.get("reason")
    if (
        not isinstance(change, str)
        or not change.strip()
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        return None
    return {"id": str(action.id), "title": change[:200], "reason": reason[:2000]}


def can_resume(ticket: _TICKET, evidence: dict[str, Any]) -> bool:
    loop = evidence.get("loop")
    return (
        not is_closed(ticket) and isinstance(loop, dict) and loop.get("state") == "dispatch_failed"
    )


def current_production_state(ticket: _TICKET, evidence: dict[str, Any]) -> tuple[str, str | None]:
    """Read the owned durable snapshot, never another worker's stale in-memory status."""
    from modstore_server.workbench_api import _load_workbench_session_unlocked

    generation = str(current_delivery_run(evidence).get("session_id") or "")
    snapshot = _load_workbench_session_unlocked(generation) if generation else None
    if not snapshot or not delivery_snapshot_matches(snapshot, ticket, generation):
        return generation, None
    status = snapshot.get("status")
    return generation, (
        status if isinstance(status, str) and status in {"running", "done", "error"} else None
    )


def observation(
    ticket: _TICKET,
    evidence: dict[str, Any],
    change: dict[str, str] | None,
    now: datetime,
) -> tuple[str, str | None]:
    """Only compare persisted business signals. A new prose summary is not a status change."""
    closed = is_closed(ticket)
    due = utc_time(ticket.expected_completion_at)
    overdue = not closed and due is not None and due <= now
    resolution = evidence.get("resolution")
    runtime_state = resolution.get("state") if isinstance(resolution, dict) else None
    acceptance = evidence.get("acceptance_status")
    active_generation = evidence.get("delivery_generation")
    receipts = [
        (row.get("receipt_id"), row.get("stage"), row.get("verified") is True)
        for row in evidence.get("receipt_events") or []
        if isinstance(row, dict) and row.get("generation") == active_generation
    ]
    delivered = is_delivered(ticket, evidence)
    production = ("", None) if closed else current_production_state(ticket, evidence)
    reasons = []
    if not closed:
        if change:
            reasons.append("有敏感操作等你审阅。")
        elif can_resume(ticket, evidence):
            reasons.append("负责员工暂不可用，工单停在待派单。")
        elif (
            runtime_state in {"queued_rework", "repair_failed"}
            or evidence.get("start_error")
            or production[1] == "error"
        ):
            reasons.append("交付需要返工。")
        if overdue:
            reasons.append("已过工单记录的预计完成时间。")
    reason = "".join(reasons) or None
    fields = (
        ticket.status,
        change["id"] if change else None,
        acceptance,
        receipts,
        delivered,
        runtime_state,
        production,
        reason,
        iso(due) if overdue else None,
    )
    return hashlib.sha256(json_dumps(fields).encode()).hexdigest(), reason


async def item_for(db: Session, ticket: _TICKET, user_id: int, following: bool) -> dict[str, Any]:
    from modstore_server.customer_service_delivery_api import _custom_delivery_payload

    change = pending_change(db, ticket, user_id)
    if not owns_delivery(ticket, user_id):
        # Review authority exposes the request, not the customer's history or production data.
        return {
            "ticket_id": int(ticket.id),
            "ticket_no": ticket.ticket_no,
            "title": change["title"] if change else "审批已处理",
            "stage_label": "待独立审核" if change else "审批已处理",
            "expected_completion_at": None,
            "following": False,
            "can_follow": False,
            "needs_attention": change is not None,
            "attention_reason": "有敏感操作等你审阅。" if change else None,
            "can_resume": False,
            "approval_id": change["id"] if change else None,
            "approval_title": change["title"] if change else None,
            "approval_reason": change["reason"] if change else None,
        }
    evidence = custom_delivery_evidence(ticket)
    closed = is_closed(ticket)
    _, reason = observation(ticket, evidence, change, datetime.now(UTC))
    delivery = (await _custom_delivery_payload(ticket, include_run_history=False))[
        "custom_delivery"
    ]
    stage, label = delivery["stage"], delivery["stage_label"]
    if closed and not is_delivered(ticket, evidence):
        stage, label = "closed", "工单已结束，未记录交付完成回执"
    elif stage == "rework":
        label = "交付需要返工"
    return {
        "ticket_id": int(ticket.id),
        "ticket_no": ticket.ticket_no,
        "title": ticket.title or ticket.ticket_no,
        "status": ticket.status,
        "stage": stage,
        "stage_label": label,
        "expected_completion_at": iso(ticket.expected_completion_at),
        "updated_at": iso(ticket.updated_at),
        "following": following,
        "can_follow": True,
        "needs_attention": reason is not None,
        "attention_reason": reason,
        "can_resume": can_resume(ticket, evidence),
        "approval_id": change["id"] if change else None,
        "approval_title": change["title"] if change else None,
        "approval_reason": change["reason"] if change else None,
    }


def event_timeline(db: Session, ticket: _TICKET) -> list[dict[str, Any]]:
    def event(ident, kind, label, at, status=None):
        return {"id": ident, "kind": kind, "label": label, "at": at, "status": status}

    events = [event("created", "ticket", "工单已受理", iso(ticket.created_at))]
    audits = (
        db.query(CustomerServiceAuditLog)
        .filter(
            CustomerServiceAuditLog.ticket_id == ticket.id,
            CustomerServiceAuditLog.event_type.in_(_AUDIT_LABELS),
        )
        .order_by(CustomerServiceAuditLog.id.desc())
        .limit(40)
    )
    for row in audits:
        kind = str(row.event_type)
        events.append(
            event(
                f"audit-{row.id}",
                kind,
                _AUDIT_LABELS[kind],
                iso(row.created_at),
            )
        )
    actions = (
        db.query(CustomerServiceAction)
        .filter(CustomerServiceAction.ticket_id == ticket.id)
        .order_by(CustomerServiceAction.id.desc())
        .limit(40)
    )
    for action in actions:
        events.append(
            event(
                f"action-{action.id}",
                "action",
                _ACTION_LABELS.get(str(action.action_type), "工单操作"),
                iso(action.updated_at or action.created_at),
                action.status,
            )
        )
    evidence = custom_delivery_evidence(ticket)
    for receipt in evidence.get("receipt_events") or []:
        if isinstance(receipt, dict) and receipt.get("stage") in _RECEIPT_LABELS:
            stage = receipt["stage"]
            events.append(
                event(
                    f"receipt-{receipt.get('receipt_id')}",
                    "receipt",
                    _RECEIPT_LABELS[stage],
                    receipt.get("received_at"),
                    "verified" if receipt.get("verified") is True else stage,
                )
            )
    if is_delivered(ticket, evidence):
        events.append(
            event(
                "delivered",
                "receipt",
                "交付已完成",
                evidence["delivered_at"],
                "verified",
            )
        )
    return sorted(events, key=lambda row: str(row["at"] or ""), reverse=True)[:50]


def set_following(db: Session, ticket: _TICKET, user_id: int, following: bool) -> None:
    watch = db.get(_WATCH, (user_id, int(ticket.id)))
    if (watch is not None and watch.following == following) or (watch is None and not following):
        return
    now = datetime.now(UTC)
    change = pending_change(db, ticket, user_id)
    observed, _ = observation(ticket, custom_delivery_evidence(ticket), change, now)
    if watch is None:
        db.add(
            _WATCH(
                user_id=user_id,
                ticket_id=ticket.id,
                last_observed=observed,
                following=True,
                next_check_at=now + timedelta(minutes=5),
            )
        )
    else:
        watch.following = following
        watch.last_observed = observed
        watch.next_check_at = now + timedelta(minutes=5)
        watch.version += 1
    db.commit()


def check_delivery_followups(db: Session, *, now: datetime, limit: int = 100) -> int:
    """Persist the cursor and in-app notification atomically, including across scheduler processes."""
    due = (
        db.query(_WATCH)
        .filter(_WATCH.following.is_(True), _WATCH.next_check_at <= now)
        .order_by(_WATCH.next_check_at, _WATCH.user_id, _WATCH.ticket_id)
        .limit(limit)
        .all()
    )
    for watch in due:
        ticket = scoped_deliveries(db, int(watch.user_id)).filter_by(id=watch.ticket_id).first()
        scope = exists().where(
            User.id == watch.user_id,
            User.is_admin.is_(True),
            User.deleted_at.is_(None),
        )
        authorized = ticket is not None and db.query(scope).scalar() is True
        values: dict[Any, Any] = {
            "next_check_at": now + timedelta(minutes=5),
            "version": watch.version + 1,
        }
        notify = False
        if authorized and ticket is not None:
            change = pending_change(db, ticket, int(watch.user_id))
            observed, reason = observation(ticket, custom_delivery_evidence(ticket), change, now)
            values["last_observed"] = observed
            notify = bool(watch.last_observed and observed != watch.last_observed)
        else:
            values["following"] = False

        claim = db.query(_WATCH).filter_by(
            user_id=watch.user_id,
            ticket_id=watch.ticket_id,
            following=True,
            version=watch.version,
        )
        if notify and ticket is not None:
            claim = claim.filter(
                scope,
                exists().where(
                    _TICKET.id == ticket.id,
                    _TICKET.intent == "custom_delivery",
                    or_(
                        _TICKET.user_id == watch.user_id,
                        _TICKET.assigned_admin_id == watch.user_id,
                    ),
                ),
            )
        if claim.update(values, synchronize_session=False) != 1:
            continue
        if notify and ticket is not None:
            # This notification is in-app only. Reusing create_notification() would commit
            # before the cursor and may mirror the content to email.
            db.add(
                Notification(
                    user_id=watch.user_id,
                    kind="system",
                    title="小C · 交付跟进",
                    content=f"工单 {ticket.ticket_no} 状态有变化。{reason or '打开小C工作动态查看。'}",
                    data_json=json_dumps(
                        {"kind": "xiaoc_delivery_followup", "ticket_id": ticket.id}
                    ),
                )
            )
    db.commit()
    return len(due)


def run_delivery_followups() -> int:
    with get_session_factory()() as db:
        return check_delivery_followups(db, now=datetime.now(UTC))
