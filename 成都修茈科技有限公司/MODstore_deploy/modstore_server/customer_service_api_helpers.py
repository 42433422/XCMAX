# mypy: disable-error-code="arg-type"
"""Ownership checks and response serializers for the customer-service API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.customer_service_orchestrator import ticket_payload
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceIntegration,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)


def own_session_or_404(
    db: Session, user: User, session_id: int
) -> CustomerServiceSession:
    row = db.get(CustomerServiceSession, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "客服会话不存在")
    return row


def visible_ticket_or_404(
    db: Session, user: User, ticket_id: int
) -> CustomerServiceTicket:
    from modstore_server.customer_ticket_reader import TicketReader

    row = db.get(CustomerServiceTicket, ticket_id)
    if row is not None and (
        row.user_id in user.owner_ids
        if isinstance(user, TicketReader)
        else user.is_admin or row.user_id == user.id
    ):
        return row
    raise HTTPException(404, "客服工单不存在")


def standard_payload(
    row: CustomerServiceStandard, *, include_policy: bool = False
) -> dict[str, Any]:
    payload = {
        **{
            name: getattr(row, name)
            for name in ["id", "name", "scenario", "description", "auto_enabled", "risk_level", "priority"]
        },
        "rules": json_loads(row.rules_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
    if include_policy:
        payload["action_policy"] = json_loads(row.action_policy_json, {})
    return payload


def integration_payload(row: CustomerServiceIntegration) -> dict[str, Any]:
    return {
        **{
            name: getattr(row, name)
            for name in ["id", "name", "integration_type", "connector_id", "workflow_id", "scenario", "enabled", "created_by"]
        },
        "config": json_loads(row.config_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def audit_payload(row: CustomerServiceAuditLog) -> dict[str, Any]:
    fields = ["id", "ticket_id", "session_id", "actor_user_id", "actor_type", "event_type"]
    return {
        **{name: getattr(row, name) for name in fields},
        "detail": json_loads(row.detail_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def close_ticket_with_evidence(
    db: Session, user: User, ticket_id: int, request: dict[str, str]
):
    ticket = visible_ticket_or_404(db, user, ticket_id)
    key = f"admin-ticket-close:{ticket_id}:{request['request_id']}"
    existing = db.query(CustomerServiceAction).filter_by(idempotency_key=key).first()
    if existing:
        if json_loads(existing.request_json, {}) != request:
            raise HTTPException(409, "同一关单请求标识不能用于不同内容")
        if ticket.status != "resolved" or not ticket.closed_at:
            raise HTTPException(409, "原工单状态已变化，不能重放关单结果")
        return {"ticket": ticket_payload(ticket), "replayed": True}
    if ticket.status != "processing" or ticket.closed_at:
        raise HTTPException(409, "只有处理中且未关闭的工单可以验收关单")
    if len(request["note"].strip()) < 8 or len(request["verification"].strip()) < 20:
        raise HTTPException(422, "处理结论和实际验收证据不能为空")

    now = datetime.now(UTC)
    evidence = json_loads(ticket.evidence_json, {})
    resolution = evidence.get("resolution")
    if not isinstance(resolution, dict):
        resolution = {}
    resolution.update(
        state="resolved",
        resolved_at=now.isoformat(),
        verification_mode="admin_runtime",
        verification_summary=request["verification"].strip(),
        resolution_note=request["note"].strip(),
        repair_verified=True,
    )
    evidence["resolution"] = resolution
    db.query(CustomerServiceTicket).filter_by(id=ticket_id).update(
        {"evidence_json": json_dumps(evidence), "status": "resolved", "closed_at": now, "updated_at": now}
    )
    db.add(
        CustomerServiceAction(
            ticket_id=ticket.id,
            user_id=user.id,
            action_type="ticket.close",
            target_type="ticket",
            target_id=str(ticket.id),
            status="completed",
            request_json=json_dumps(request),
            result_json=json_dumps(
                {"status": "resolved", "closed_at": now.isoformat()}
            ),
            idempotency_key=key,
        )
    )
    audit(
        db,
        actor=user,
        actor_type="admin",
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        event_type="admin_ticket_closed",
        detail={
            "note": request["note"].strip(),
            "verification": request["verification"].strip(),
        },
    )
    db.commit()
    return {"ticket": ticket_payload(ticket), "replayed": False}
