# mypy: disable-error-code="arg-type"
"""Ownership checks and response serializers for the customer-service API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import audit, json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceAuditLog,
    CustomerServiceIntegration,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)


def own_session_or_404(db: Session, user: User, session_id: int) -> CustomerServiceSession:
    row = db.get(CustomerServiceSession, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "客服会话不存在")
    return row


def visible_ticket_or_404(db: Session, user: User, ticket_id: int) -> CustomerServiceTicket:
    from modstore_server.customer_ticket_reader import TicketReader

    row = db.get(CustomerServiceTicket, ticket_id)
    if row is not None and (
        row.user_id in user.owner_ids
        if isinstance(user, TicketReader)
        else user.is_admin or row.user_id == user.id
    ):
        return row
    raise HTTPException(404, "客服工单不存在")


def update_expected_completion(
    db: Session, ticket_id: int, user: User, value: datetime | None
) -> CustomerServiceTicket:
    ticket = visible_ticket_or_404(db, user, ticket_id)
    value = (
        value.replace(tzinfo=UTC)
        if value and value.tzinfo is None
        else (value.astimezone(UTC) if value else None)
    )
    ticket.expected_completion_at = value  # type: ignore[assignment]
    audit(
        db,
        event_type="expected_completion_updated",
        detail={"expected_completion_at": value.isoformat() if value else None},
        actor=user,
        ticket_id=ticket.id,
        actor_type="admin",
    )
    db.commit()
    db.refresh(ticket)
    return ticket


def standard_payload(
    row: CustomerServiceStandard, *, include_policy: bool = False
) -> Dict[str, Any]:
    payload = {
        "id": row.id,
        "name": row.name,
        "scenario": row.scenario,
        "description": row.description,
        "auto_enabled": row.auto_enabled,
        "risk_level": row.risk_level,
        "priority": row.priority,
        "rules": json_loads(row.rules_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
    if include_policy:
        payload["action_policy"] = json_loads(row.action_policy_json, {})
    return payload


def integration_payload(row: CustomerServiceIntegration) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "integration_type": row.integration_type,
        "connector_id": row.connector_id,
        "workflow_id": row.workflow_id,
        "scenario": row.scenario,
        "config": json_loads(row.config_json, {}),
        "enabled": row.enabled,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def audit_payload(row: CustomerServiceAuditLog) -> Dict[str, Any]:
    fields = "id ticket_id session_id actor_user_id actor_type event_type".split()
    return {
        **{name: getattr(row, name) for name in fields},
        "detail": json_loads(row.detail_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
