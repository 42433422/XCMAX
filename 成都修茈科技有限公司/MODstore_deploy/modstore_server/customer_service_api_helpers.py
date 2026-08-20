# mypy: disable-error-code="arg-type"
"""Ownership checks and response serializers for the customer-service API."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceAuditLog,
    CustomerServiceIntegration,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)


def own_session_or_404(db: Session, user: User, session_id: int) -> CustomerServiceSession:
    row = (
        db.query(CustomerServiceSession)
        .filter(
            CustomerServiceSession.id == session_id,
            CustomerServiceSession.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "客服会话不存在")
    return row


def visible_ticket_or_404(db: Session, user: User, ticket_id: int) -> CustomerServiceTicket:
    query = db.query(CustomerServiceTicket).filter(CustomerServiceTicket.id == ticket_id)
    if not user.is_admin:
        query = query.filter(CustomerServiceTicket.user_id == user.id)
    row = query.first()
    if not row:
        raise HTTPException(404, "客服工单不存在")
    return row


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
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "session_id": row.session_id,
        "actor_user_id": row.actor_user_id,
        "actor_type": row.actor_type,
        "event_type": row.event_type,
        "detail": json_loads(row.detail_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


__all__ = [
    "audit_payload",
    "integration_payload",
    "own_session_or_404",
    "standard_payload",
    "visible_ticket_or_404",
]
