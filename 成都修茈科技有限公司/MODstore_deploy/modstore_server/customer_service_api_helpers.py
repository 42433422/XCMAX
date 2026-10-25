# mypy: disable-error-code="arg-type"
"""Ownership checks and response serializers for the customer-service API."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from modstore_server.customer_service_orchestrator import ticket_payload
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceIntegration,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)


class TicketTitleBody(BaseModel, extra="forbid"):
    title: str = Field(..., min_length=1, max_length=256)
    expected_title: str = Field(..., max_length=256)
    intent: Literal["product_issue"] | None = None
    expected_intent: Literal["account_support", "general"] | None = None
    reason: str = Field(default="", max_length=2000)


class TicketReplyBody(BaseModel, extra="forbid"):
    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    note: str = Field(min_length=4, max_length=2000)


def reply_to_ticket(db: Session, user: User, ticket_id: int, body: TicketReplyBody):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    ticket = visible_ticket_or_404(db, user, ticket_id)
    db.refresh(ticket, with_for_update=True)
    note = body.note.strip()
    if len(note) < 4:
        raise HTTPException(422, "答复至少4字")
    key = f"admin-ticket-reply:{ticket_id}:{body.request_id.lower()}"
    existing = db.query(CustomerServiceAction).filter_by(idempotency_key=key).first()
    if existing:
        if json_loads(existing.request_json, {}) != {"note": note}:
            raise HTTPException(409, "同一答复标识不能用于不同内容")
        return {"ticket": ticket_payload(ticket), "replayed": True}
    if ticket.status != "processing" or ticket.closed_at:
        raise HTTPException(409, "仅可答复未关闭的原工单")
    session = db.get(CustomerServiceSession, ticket.session_id)
    if session is None or session.user_id != ticket.user_id:
        raise HTTPException(409, "原客服会话归属不可核验")
    now = datetime.now(UTC)
    db.add(
        CustomerServiceMessage(
            session_id=session.id,
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            role="assistant",
            content=note,
            created_at=now,
            payload_json=json_dumps(
                {"origin": "admin_reply", "operator_user_id": user.id}
            ),
        )
    )
    db.add(
        CustomerServiceAction(
            ticket_id=ticket.id,
            user_id=user.id,
            action_type="ticket.reply",
            target_type="session",
            target_id=str(session.id),
            status="completed",
            request_json=json_dumps({"note": note}),
            result_json=json_dumps({"session_id": session.id}),
            idempotency_key=key,
        )
    )
    setattr(session, "last_message", note)
    setattr(session, "updated_at", now)
    setattr(ticket, "updated_at", now)
    audit(
        db,
        actor=user,
        actor_type="admin",
        ticket_id=ticket.id,
        session_id=session.id,
        event_type="admin_ticket_replied",
        detail={"note": note, "request_id": body.request_id},
    )
    db.commit()
    return {"ticket": ticket_payload(ticket), "replayed": False}


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


def _row_payload(row: Any, fields: str) -> dict[str, Any]:
    return {
        **{name: getattr(row, name) for name in fields.split()},
        **{
            name: getattr(row, name).isoformat() if getattr(row, name) else ""
            for name in ("created_at", "updated_at")
            if hasattr(row, name)
        },
    }


def standard_payload(
    row: CustomerServiceStandard, *, include_policy: bool = False
) -> dict[str, Any]:
    payload = _row_payload(
        row, "id name scenario description auto_enabled risk_level priority"
    )
    payload["rules"] = json_loads(row.rules_json, {})
    if include_policy:
        payload["action_policy"] = json_loads(row.action_policy_json, {})
    return payload


def integration_payload(row: CustomerServiceIntegration) -> dict[str, Any]:
    return {
        **_row_payload(
            row,
            "id name integration_type connector_id workflow_id scenario enabled created_by",
        ),
        "config": json_loads(row.config_json, {}),
    }


def audit_payload(row: CustomerServiceAuditLog) -> dict[str, Any]:
    return {
        **_row_payload(
            row, "id ticket_id session_id actor_user_id actor_type event_type"
        ),
        "detail": json_loads(row.detail_json, {}),
    }


def close_ticket_with_evidence(
    db: Session, user: User, ticket_id: int, request: dict[str, str]
):
    ticket = visible_ticket_or_404(db, user, ticket_id)
    disposition = request.get("disposition", "resolved")
    expired = disposition == "expired"
    evidence = json_loads(ticket.evidence_json, {})
    from modstore_server.customer_issue_delivery_contract import issue_resolution

    if not expired and (
        ticket.intent == "product_issue"
        or issue_resolution(ticket, evidence).get("route") == "private_mod"
        or evidence.get("delivery_managed_by") == "custom_delivery"
    ):
        raise HTTPException(
            409, "产品问题和定制交付必须由原客户通过运行回执或原工单决策完成验收"
        )
    key = f"admin-ticket-close:{ticket_id}:{request['request_id']}"
    existing = db.query(CustomerServiceAction).filter_by(idempotency_key=key).first()
    if existing:
        previous = json_loads(existing.request_json, {})
        previous.setdefault("disposition", "resolved")
        if previous != {**request, "disposition": disposition}:
            raise HTTPException(409, "同一关单请求标识不能用于不同内容")
        if ticket.status != disposition or not ticket.closed_at:
            raise HTTPException(409, "原工单状态已变化，不能重放关单结果")
        return {"ticket": ticket_payload(ticket), "replayed": True}
    if ticket.status != "processing" or ticket.closed_at:
        raise HTTPException(409, "只有处理中且未关闭的工单可以验收关单")
    if len(request["note"].strip()) < 8 or len(request["verification"].strip()) < 20:
        raise HTTPException(422, "处理结论和实际验收证据不能为空")
    if expired:
        today = datetime.now(UTC) + timedelta(hours=8)
        year, month = divmod(today.year * 12 + today.month - 3, 12)
        cutoff = datetime(
            year, month + 1, min(today.day, monthrange(year, month + 1)[1])
        ) - timedelta(hours=8)
        recent = (
            max(ticket.created_at, ticket.updated_at or ticket.created_at) >= cutoff
        )
        for model in (
            CustomerServiceAuditLog,
            CustomerServiceMessage,
            CustomerServiceAction,
        ):
            recent |= (
                db.query(model.id)
                .filter(
                    model.ticket_id == ticket_id,
                    or_(
                        model.created_at >= cutoff,
                        getattr(model, "updated_at", model.created_at) >= cutoff,
                    ),
                )
                .first()
                is not None
            )
        if recent or ticket.intent == "custom_delivery":
            raise HTTPException(409, "仅可处置超过两个月且无后续活动的非定制旧单")

    session = db.get(CustomerServiceSession, ticket.session_id)
    if session is None or session.user_id != ticket.user_id:
        raise HTTPException(409, "原客服会话不可核验，不能关闭工单")
    now = datetime.now(UTC)
    resolution = evidence.get("resolution")
    if not isinstance(resolution, dict):
        resolution = {}
    resolution.update(
        state=disposition,
        verification_mode="admin_expiry" if expired else "admin_runtime",
        verification_summary=request["verification"].strip(),
        resolution_note=request["note"].strip(),
        repair_verified=not expired,
    )
    resolution.pop("resolved_at" if expired else "expired_at", None)
    resolution["expired_at" if expired else "resolved_at"] = now.isoformat()
    evidence["resolution"] = resolution
    setattr(ticket, "evidence_json", json_dumps(evidence))
    setattr(ticket, "status", disposition)
    setattr(ticket, "closed_at", now)
    setattr(ticket, "updated_at", now)
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
                {"status": disposition, "closed_at": now.isoformat()}
            ),
            idempotency_key=key,
        )
    )
    notice = f"工单 {ticket.ticket_no}：{'已过期不再处理（未修复，资金权益不变）' if expired else '管理员验收并关闭'}。{request['note'].strip()}"
    db.add(
        CustomerServiceMessage(
            session_id=ticket.session_id,
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            role="assistant",
            content=notice,
            created_at=now,
        )
    )
    setattr(session, "last_message", notice)
    setattr(session, "updated_at", now)
    audit(
        db,
        actor=user,
        actor_type="admin",
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        event_type="admin_ticket_expired" if expired else "admin_ticket_closed",
        detail={
            "note": request["note"].strip(),
            "verification": request["verification"].strip(),
        },
    )
    db.commit()
    return {"ticket": ticket_payload(ticket), "replayed": False}


def correct_ticket_metadata(
    db: Session, user: User, ticket_id: int, body: TicketTitleBody
) -> dict[str, Any]:
    ticket = visible_ticket_or_404(db, user, ticket_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "工单标题不能为空")
    correction = body.intent is not None
    if correction:
        if body.expected_intent is None or len(body.reason.strip()) < 8:
            raise HTTPException(422, "分类修正须提供原分类和至少8字的原因")
        if ticket.status != "processing" or ticket.closed_at:
            raise HTTPException(409, "只能纠正处理中且未关闭的原工单分类")
    elif body.expected_intent is not None or body.reason.strip():
        raise HTTPException(422, "分类修正参数不完整")
    updates = {"title": title, **({"intent": body.intent} if correction else {})}
    if any(getattr(ticket, key) != value for key, value in updates.items()):
        filters = [
            CustomerServiceTicket.id == ticket_id,
            CustomerServiceTicket.title == body.expected_title,
        ]
        if correction:
            filters += [
                CustomerServiceTicket.intent == body.expected_intent,
                CustomerServiceTicket.status == "processing",
                CustomerServiceTicket.closed_at.is_(None),
            ]
        changed = (
            db.query(CustomerServiceTicket)
            .filter(*filters)
            .update(updates, synchronize_session=False)
        )
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "工单标题、分类或状态已变化，请刷新后重试")
        detail = {"old_title": body.expected_title, "new_title": title}
        if correction:
            detail.update(
                old_intent=body.expected_intent,
                new_intent=body.intent,
                reason=body.reason.strip(),
            )
        audit(
            db,
            actor=user,
            actor_type="admin",
            ticket_id=ticket_id,
            session_id=ticket.session_id,
            event_type=f"ticket_{'classification' if correction else 'title'}_corrected",
            detail=detail,
        )
        db.commit()
    return {"ticket": {"id": ticket_id, **updates}}
