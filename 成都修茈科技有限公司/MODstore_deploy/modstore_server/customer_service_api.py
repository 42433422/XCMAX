# mypy: disable-error-code="arg-type, assignment"
# isort: skip_file
# ruff: noqa: E402
"""独立 AI 客服平台 API。"""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
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
    IntegrationBody,
    TicketTitleBody,
    TicketReplyBody,
    reply_to_ticket,
    correct_ticket_metadata,
    StandardBody,
    close_ticket_with_evidence,
    audit_payload as _audit_payload,
    integration_payload as _integration_payload,
    own_session_or_404 as _own_session_or_404,
    standard_payload as _standard_payload,
    update_expected_completion as _update_expected_completion,
    visible_ticket_or_404 as _visible_ticket_or_404,
)
from modstore_server import customer_service_customer_view as customer_view
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import User
from modstore_server.customer_ticket_reader import (
    TicketReader,
    reader_ticket,
    reader_detail,
)
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


class CustomerTicketEtaBody(BaseModel):
    expected_completion_at: Optional[datetime]


class AdminTicketCloseBody(BaseModel, extra="forbid"):
    disposition: Literal["resolved", "expired"] = "resolved"
    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    note: str = Field(min_length=8, max_length=2000)
    verification: str = Field(min_length=20, max_length=4000)


def _configuration_values(body: BaseModel) -> Dict[str, Any]:
    values = body.model_dump()
    for name, value in tuple(values.items()):
        if isinstance(value, str):
            values[name] = value.strip()
        elif name in {"rules", "action_policy", "config"}:
            values[name + "_json"] = json_dumps(values.pop(name))
    for name, default in (
        ("scenario", "general"),
        ("risk_level", "low"),
        ("integration_type", "openapi"),
    ):
        if name in values:
            values[name] = values[name] or default
    return values


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
    return result if user.is_admin else customer_view.customer_chat_result(result)


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
    rows = [
        {
            "id": m.id,
            "ticket_id": m.ticket_id,
            "role": m.role,
            "content": m.content,
            "payload": json_loads(m.payload_json, {}),
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in messages
    ]
    if not user.is_admin:
        rows = [customer_view.customer_message(m) for m in rows]
    return {"session": session_payload(session), "messages": rows}


@router.get("/tickets")
async def list_tickets(
    status: str = "",
    intent: str = Query("", max_length=64),
    submitter_type: str = Query("", max_length=16),
    search: str = Query("", max_length=200),
    source_ref: str = Query("", max_length=128),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(CustomerServiceTicket)
    if isinstance(user, TicketReader):
        q = q.filter(CustomerServiceTicket.user_id.in_(user.owner_ids))
    elif not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    if source_ref:
        from modstore_server.customer_issue_intake import request_identity

        if isinstance(user, TicketReader):
            raise HTTPException(403, "工单受理回查需要提交账号身份")
        q = q.filter(
            CustomerServiceTicket.user_id == user.id,
            CustomerServiceTicket.ticket_no == request_identity(user.id, "customer_feedback", source_ref),
        )
    if status:
        q = q.filter(CustomerServiceTicket.status == status)
    # 分类筛选只对管理端启用；客户仍只能读取自己的工单。
    if user.is_admin and intent.strip():
        q = q.filter(CustomerServiceTicket.intent == intent.strip().lower())
    # 客户侧仍只按本人 user_id 查询；身份筛选只开放给管理端，不能扩大客户可见范围。
    if user.is_admin and submitter_type.strip():
        kind = submitter_type.strip().lower()
        if kind not in {"admin", "customer", "unknown"}:
            raise HTTPException(status_code=422, detail="提交人身份筛选条件无效")
        q = q.filter(CustomerServiceTicket.submitter_type == kind)
    term = search.strip()
    if term:
        matches = [
            column.contains(term, autoescape=True)
            for column in (
                CustomerServiceTicket.ticket_no,
                CustomerServiceTicket.title,
                CustomerServiceTicket.summary,
            )
        ]
        if term.isascii() and term.isdigit() and len(term) <= 18:
            matches.append(CustomerServiceTicket.id == int(term))
        q = q.filter(or_(*matches))
    total = q.count()
    rows = (
        q.order_by(CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    view = ticket_payload if user.is_admin else customer_view.customer_ticket_row
    payload = {
        "items": [
            reader_ticket(db, r) if isinstance(user, TicketReader) else view(r) for r in rows
        ],
        "total": total,
        "offset": offset,
    }
    if isinstance(user, TicketReader):
        payload.update(scope=user.scope(), limit=limit, has_more=offset + len(rows) < total)
    return payload


@router.put("/tickets/{ticket_id}/title")
async def correct_ticket_title(
    ticket_id: int,
    body: TicketTitleBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    return correct_ticket_metadata(db, user, ticket_id, body)


@router.post("/tickets/{ticket_id}/reply")
async def reply_to_ticket_as_admin(
    ticket_id: int,
    body: TicketReplyBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    return reply_to_ticket(db, user, ticket_id, body)


@router.post("/tickets/{ticket_id}/close")
async def close_ticket_as_admin(
    ticket_id: int,
    body: AdminTicketCloseBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    return close_ticket_with_evidence(db, user, ticket_id, body.model_dump())


@router.get("/tickets/{ticket_id}")
async def ticket_detail(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if isinstance(user, TicketReader):
        return reader_detail(db, ticket, user)

    def related(model: Any, descending: bool = False) -> list[Any]:
        order = model.id.desc() if descending else model.id.asc()
        return list(db.query(model).filter(model.ticket_id == ticket.id).order_by(order).all())

    decisions = [decision_payload(d) for d in related(CustomerServiceDecision, True)]
    actions = [action_payload(a) for a in related(CustomerServiceAction)]
    from modstore_server.customer_ticket_execution import ticket_execution_overview

    return {
        **({"execution_overview": ticket_execution_overview(db, ticket)} if user.is_admin else {}),
        "ticket": (
            ticket_payload(ticket) if user.is_admin else customer_view.customer_ticket_row(ticket)
        ),
        "decisions": (
            decisions if user.is_admin else [customer_view.customer_decision(d) for d in decisions]
        ),
        "actions": actions if user.is_admin else customer_view.customer_actions(actions),
        "audit_logs": (
            [_audit_payload(a) for a in related(CustomerServiceAuditLog)] if user.is_admin else []
        ),
    }


@router.patch("/tickets/{ticket_id}/expected-completion", dependencies=[Depends(_require_admin)])
async def update_ticket_expected_completion(
    ticket_id: int,
    body: CustomerTicketEtaBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _update_expected_completion(db, ticket_id, user, body.expected_completion_at)
    return {"ticket": ticket_payload(ticket)}


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
    rows = [action_payload(r) for r in q.order_by(CustomerServiceAction.id.desc()).limit(limit)]
    return {"items": rows if user.is_admin else customer_view.customer_actions(rows)}


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
    row = CustomerServiceStandard(**_configuration_values(body), created_by=user.id)
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
    for key, value in _configuration_values(body).items():
        setattr(row, key, value)
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
    row = CustomerServiceIntegration(**_configuration_values(body), created_by=user.id)
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
    for key, value in _configuration_values(body).items():
        setattr(row, key, value)
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
