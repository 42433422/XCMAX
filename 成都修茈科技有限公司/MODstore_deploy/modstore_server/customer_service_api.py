"""独立 AI 客服平台 API。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db, require_admin
from modstore_server.customer_service_orchestrator import (
    action_payload,
    decision_payload,
    handle_customer_message,
    session_payload,
    ticket_payload,
)
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceDecision,
    CustomerServiceIntegration,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)

router = APIRouter(prefix="/api/customer-service", tags=["customer-service"])

_get_current_user = get_current_user
_require_admin = require_admin


class CustomerServiceChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[int] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class StandardBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scenario: str = Field(default="general", max_length=64)
    description: str = Field(default="", max_length=4000)
    rules: Dict[str, Any] = Field(default_factory=dict)
    action_policy: Dict[str, Any] = Field(default_factory=dict)
    auto_enabled: bool = True
    risk_level: str = Field(default="low", max_length=16)
    priority: int = 100


class IntegrationBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    integration_type: str = Field(default="openapi", max_length=32)
    connector_id: Optional[int] = None
    workflow_id: Optional[int] = None
    scenario: str = Field(default="general", max_length=64)
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


@router.post("/chat")
async def customer_service_chat(
    body: CustomerServiceChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    result = handle_customer_message(
        db,
        user=user,
        message=body.message,
        session_id=body.session_id,
        context=body.context,
    )
    db.commit()
    try:
        from modstore_server.incident_bus import publish as publish_incident

        t = result.get("ticket") if isinstance(result.get("ticket"), dict) else {}
        if t:
            payload = {
                "subject_id": str(t.get("ticket_no") or t.get("id") or ""),
                "ticket_id": int(t.get("id") or 0),
                "ticket_no": str(t.get("ticket_no") or "")[:128],
                "title": str(t.get("title") or "")[:500],
                "intent": str(t.get("intent") or "")[:64],
                "status": str(t.get("status") or "")[:32],
                "summary": str(t.get("summary") or "")[:2000],
                "user_id": int(user.id or 0),
                "session_id": int((result.get("session") or {}).get("id") or 0),
            }
            publish_incident(
                "ops.intake.customer_ticket",
                payload,
                source="customer-service-api",
                fingerprint=None,
            )
    except Exception:
        pass
    return result


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(CustomerServiceSession)
        .filter(CustomerServiceSession.user_id == user.id)
        .order_by(CustomerServiceSession.updated_at.desc(), CustomerServiceSession.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [session_payload(r) for r in rows]}


@router.get("/sessions/{session_id}")
async def session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    session = _own_session_or_404(db, user, session_id)
    messages = (
        db.query(CustomerServiceMessage)
        .filter(CustomerServiceMessage.session_id == session.id)
        .order_by(CustomerServiceMessage.id.asc())
        .all()
    )
    return {
        "session": session_payload(session),
        "messages": [
            {
                "id": m.id,
                "ticket_id": m.ticket_id,
                "role": m.role,
                "content": m.content,
                "payload": json_loads(m.payload_json, {}),
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in messages
        ],
    }


@router.get("/tickets")
async def list_tickets(
    status: str = "",
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(CustomerServiceTicket)
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    if status:
        q = q.filter(CustomerServiceTicket.status == status)
    rows = (
        q.order_by(CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [ticket_payload(r) for r in rows]}


@router.get("/tickets/{ticket_id}")
async def ticket_detail(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    decisions = (
        db.query(CustomerServiceDecision)
        .filter(CustomerServiceDecision.ticket_id == ticket.id)
        .order_by(CustomerServiceDecision.id.desc())
        .all()
    )
    actions = (
        db.query(CustomerServiceAction)
        .filter(CustomerServiceAction.ticket_id == ticket.id)
        .order_by(CustomerServiceAction.id.asc())
        .all()
    )
    audits = (
        db.query(CustomerServiceAuditLog)
        .filter(CustomerServiceAuditLog.ticket_id == ticket.id)
        .order_by(CustomerServiceAuditLog.id.asc())
        .all()
    )
    return {
        "ticket": ticket_payload(ticket),
        "decisions": [decision_payload(d) for d in decisions],
        "actions": [action_payload(a) for a in actions],
        "audit_logs": [_audit_payload(a) for a in audits],
    }


@router.get("/actions")
async def list_actions(
    ticket_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(CustomerServiceAction)
    if ticket_id:
        ticket = _visible_ticket_or_404(db, user, ticket_id)
        q = q.filter(CustomerServiceAction.ticket_id == ticket.id)
    elif not user.is_admin:
        q = q.join(
            CustomerServiceTicket, CustomerServiceAction.ticket_id == CustomerServiceTicket.id
        ).filter(CustomerServiceTicket.user_id == user.id)
    rows = q.order_by(CustomerServiceAction.id.desc()).limit(limit).all()
    return {"items": [action_payload(r) for r in rows]}


@router.get("/standards")
async def list_standards(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = db.query(CustomerServiceStandard).order_by(CustomerServiceStandard.priority.asc()).all()
    return {"items": [_standard_payload(r, include_policy=user.is_admin) for r in rows]}


@router.post("/standards")
async def create_standard(
    body: StandardBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = CustomerServiceStandard(
        name=body.name.strip(),
        scenario=body.scenario.strip() or "general",
        description=body.description.strip(),
        rules_json=json_dumps(body.rules),
        action_policy_json=json_dumps(body.action_policy),
        auto_enabled=body.auto_enabled,
        risk_level=body.risk_level.strip() or "low",
        priority=body.priority,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _standard_payload(row, include_policy=True)


@router.put("/standards/{standard_id}")
async def update_standard(
    standard_id: int,
    body: StandardBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = (
        db.query(CustomerServiceStandard).filter(CustomerServiceStandard.id == standard_id).first()
    )
    if not row:
        raise HTTPException(404, "审核标准不存在")
    row.name = body.name.strip()
    row.scenario = body.scenario.strip() or "general"
    row.description = body.description.strip()
    row.rules_json = json_dumps(body.rules)
    row.action_policy_json = json_dumps(body.action_policy)
    row.auto_enabled = body.auto_enabled
    row.risk_level = body.risk_level.strip() or "low"
    row.priority = body.priority
    db.commit()
    db.refresh(row)
    return _standard_payload(row, include_policy=True)


@router.get("/integrations")
async def list_integrations(
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    rows = db.query(CustomerServiceIntegration).order_by(CustomerServiceIntegration.id.desc()).all()
    return {"items": [_integration_payload(r) for r in rows]}


@router.post("/integrations")
async def create_integration(
    body: IntegrationBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = CustomerServiceIntegration(
        name=body.name.strip(),
        integration_type=body.integration_type.strip() or "openapi",
        connector_id=body.connector_id,
        workflow_id=body.workflow_id,
        scenario=body.scenario.strip() or "general",
        config_json=json_dumps(body.config),
        enabled=body.enabled,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _integration_payload(row)


@router.put("/integrations/{integration_id}")
async def update_integration(
    integration_id: int,
    body: IntegrationBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = (
        db.query(CustomerServiceIntegration)
        .filter(CustomerServiceIntegration.id == integration_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "集成配置不存在")
    row.name = body.name.strip()
    row.integration_type = body.integration_type.strip() or "openapi"
    row.connector_id = body.connector_id
    row.workflow_id = body.workflow_id
    row.scenario = body.scenario.strip() or "general"
    row.config_json = json_dumps(body.config)
    row.enabled = body.enabled
    db.commit()
    db.refresh(row)
    return _integration_payload(row)


def _own_session_or_404(db: Session, user: User, session_id: int) -> CustomerServiceSession:
    row = (
        db.query(CustomerServiceSession)
        .filter(CustomerServiceSession.id == session_id, CustomerServiceSession.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(404, "客服会话不存在")
    return row


def _visible_ticket_or_404(db: Session, user: User, ticket_id: int) -> CustomerServiceTicket:
    q = db.query(CustomerServiceTicket).filter(CustomerServiceTicket.id == ticket_id)
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    row = q.first()
    if not row:
        raise HTTPException(404, "客服工单不存在")
    return row


def _standard_payload(
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


def _integration_payload(row: CustomerServiceIntegration) -> Dict[str, Any]:
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


def _audit_payload(row: CustomerServiceAuditLog) -> Dict[str, Any]:
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
