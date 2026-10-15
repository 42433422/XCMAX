# mypy: disable-error-code="arg-type, assignment"
# isort: skip_file
# ruff: noqa: E402
"""独立 AI 客服平台 API。"""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS

import logging
import threading
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
from modstore_server.customer_service_api_helpers import (
    audit_payload as _audit_payload,
    integration_payload as _integration_payload,
    own_session_or_404 as _own_session_or_404,
    standard_payload as _standard_payload,
    visible_ticket_or_404 as _visible_ticket_or_404,
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customer-service", tags=["customer-service"])

_get_current_user = get_current_user
_require_admin = require_admin


def _publish_customer_ticket_incident(payload: Dict[str, Any]) -> None:
    """Fire-and-forget：工单事件派发可能跑员工编排/LLM，绝不能阻塞 /chat 响应。"""
    try:
        from modstore_server.customer_issue_intake import dispatch_pending_issue_events

        dispatch_pending_issue_events(int(payload.get("ticket_id") or 0))
    except RECOVERABLE_ERRORS:
        logger.exception("customer-service ticket incident publish failed")


def _schedule_customer_ticket_incident(payload: Dict[str, Any]) -> None:
    threading.Thread(
        target=_publish_customer_ticket_incident,
        args=(payload,),
        daemon=True,
        name="cs-ticket-incident",
    ).start()


class CustomerServiceChatBody(BaseModel):
    message: str = Field(default="", max_length=8000)
    session_id: Optional[int] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    # data:image/...;base64,... 压缩后截图，用于补充材料
    image_data_url: Optional[str] = Field(default=None, max_length=4_500_000)


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
    message = str(body.message or "").strip()
    image = str(body.image_data_url or "").strip()
    if not image:
        image = str((body.context or {}).get("image_data_url") or "").strip()
    if not message and not image:
        raise HTTPException(status_code=400, detail="请输入文字或上传图片")
    if image and not image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="图片格式无效，请上传 png/jpg/webp 等")
    if len(image) > 4_500_000:
        raise HTTPException(status_code=400, detail="图片过大，请压缩后再传")
    ctx = dict(body.context or {})
    if image:
        ctx["image_data_url"] = image
        ctx["has_image"] = True
    result = handle_customer_message(
        db,
        user=user,
        message=message or "[用户补充了图片资料]",
        session_id=body.session_id,
        context=ctx,
    )
    t = result.get("ticket") if isinstance(result.get("ticket"), dict) else {}
    if t:
        from modstore_server.customer_issue_intake import enqueue_issue

        ticket = db.get(CustomerServiceTicket, int(t.get("id") or 0))
        if ticket is not None:
            import hashlib

            revision = hashlib.sha256(
                json_dumps({"message": message, "evidence": t.get("evidence")}).encode()
            ).hexdigest()[:24]
            enqueue_issue(db, ticket, revision=revision)
            result["ticket"] = ticket_payload(ticket)
    db.commit()
    if t:
        _schedule_customer_ticket_incident({"ticket_id": int(t.get("id") or 0)})
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
            CustomerServiceTicket,
            CustomerServiceAction.ticket_id == CustomerServiceTicket.id,
        ).filter(CustomerServiceTicket.user_id == user.id)
    rows = q.order_by(CustomerServiceAction.id.desc()).limit(limit).all()
    return {"items": [action_payload(r) for r in rows]}


@router.get("/standards")
async def list_standards(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = db.query(CustomerServiceStandard).order_by(CustomerServiceStandard.priority.asc()).all()
    # SSOT 四种默认标准：库空时自愈补种（避免发布/迁库后后台空白）
    if not rows:
        try:
            from modstore_server.models_db import (
                init_default_customer_service_standards,
            )

            init_default_customer_service_standards()
            rows = (
                db.query(CustomerServiceStandard)
                .order_by(CustomerServiceStandard.priority.asc())
                .all()
            )
        except RECOVERABLE_ERRORS:
            rows = []
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


from modstore_server.customer_service_delivery_api import (  # noqa: F401
    _custom_delivery_evidence as _custom_delivery_evidence,
    router as custom_delivery_router,
)
from modstore_server.customer_service_delivery_crm_api import (
    router as custom_delivery_crm_router,
)
from modstore_server.customer_service_delivery_create_api import (
    router as custom_delivery_create_router,
)
from modstore_server.customer_service_delivery_payment_api import (
    router as custom_delivery_payment_router,
)

router.include_router(custom_delivery_router)
router.include_router(custom_delivery_crm_router)
router.include_router(custom_delivery_create_router)
router.include_router(custom_delivery_payment_router)

from modstore_server.customer_issue_api import router as customer_issue_router

router.include_router(customer_issue_router)
