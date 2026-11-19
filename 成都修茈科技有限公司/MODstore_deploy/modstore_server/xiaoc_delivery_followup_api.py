"""Management-only delivery activity and follow-up controls."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import and_
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.customer_service_tools import begin_immediate_write
from modstore_server.customer_ticket_human_ops import decide_sensitive_action
from modstore_server.customer_ticket_loop import resume_ticket_loop
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceTicket, XiaoCDeliveryFollowup
from modstore_server.xiaoc_delivery_followup import (
    event_timeline,
    item_for,
    owns_delivery,
    pending_change,
    scoped_deliveries,
    set_following,
)

router = APIRouter(prefix="/api/agent/butler/delivery-followups", tags=["butler"])


class FollowupBody(BaseModel):
    following: StrictBool


class FollowupApprovalBody(BaseModel):
    approval_id: str = Field(pattern=r"^[1-9][0-9]{0,17}$")


def _ticket(
    db: Session, ticket_id: int, user_id: int, *, write: bool = False, review: bool = False
):
    if write:
        begin_immediate_write(db)
    query = scoped_deliveries(db, user_id, include_reviews=review).filter_by(id=ticket_id)
    ticket = (query.with_for_update() if write else query).one_or_none()
    if ticket is None or (
        not owns_delivery(ticket, user_id) and not pending_change(db, ticket, user_id)
    ):
        raise HTTPException(404, "没有可查看的交付工单")
    return ticket


async def _detail(db: Session, ticket: CustomerServiceTicket, user_id: int):
    watch = db.get(XiaoCDeliveryFollowup, (user_id, int(ticket.id)))
    return {
        "item": await item_for(db, ticket, user_id, bool(watch and watch.following)),
        "events": event_timeline(db, ticket) if owns_delivery(ticket, user_id) else [],
    }


@router.get("")
async def list_delivery_followups(
    limit: int = Query(30, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    user_id = int(user.id)
    ticket, watch = CustomerServiceTicket, XiaoCDeliveryFollowup
    rows = (
        scoped_deliveries(db, user_id, include_reviews=True)
        .add_columns(watch.following)
        .outerjoin(watch, and_(watch.ticket_id == ticket.id, watch.user_id == user_id))
        .order_by(
            watch.following.desc().nulls_last(),
            ticket.updated_at.desc(),
            ticket.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return {
        "items": [
            await item_for(db, row, user_id, bool(following))
            for row, following in rows
            if owns_delivery(row, user_id) or pending_change(db, row, user_id)
        ]
    }


@router.get("/{ticket_id}")
async def get_delivery_followup(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    return await _detail(db, _ticket(db, ticket_id, int(user.id), review=True), int(user.id))


@router.put("/{ticket_id}")
async def update_delivery_followup(
    ticket_id: int,
    body: FollowupBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    user_id = int(user.id)
    ticket = _ticket(db, ticket_id, user_id, write=True)
    set_following(db, ticket, user_id, body.following)
    return await _detail(db, ticket, user_id)


@router.post("/{ticket_id}/resume")
async def resume_delivery_followup(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_service_delivery_models import (
        custom_delivery_evidence,
    )
    from modstore_server.xiaoc_delivery_followup import can_resume

    user_id = int(user.id)
    ticket = _ticket(db, ticket_id, user_id, write=True)
    if not can_resume(ticket, custom_delivery_evidence(ticket)):
        raise HTTPException(409, "当前工单不在待派单")
    result = resume_ticket_loop(db, ticket, user)
    if not result.get("ok"):
        raise HTTPException(409, "负责员工仍不可用，工单继续等待派单")
    db.commit()
    return await _detail(db, ticket, user_id)


@router.post("/{ticket_id}/approve")
async def approve_delivery_followup(
    ticket_id: int,
    body: FollowupApprovalBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    user_id = int(user.id)
    ticket = _ticket(db, ticket_id, user_id, write=True, review=True)
    change = pending_change(db, ticket, user_id)
    if not change or change["id"] != body.approval_id:
        raise HTTPException(409, "这张审批已变动，请查看最新工单")
    decide_sensitive_action(
        db,
        ticket,
        user,
        int(change["id"]),
        decision="approved",
        reason="管理端小C工作动态确认",
    )
    return await _detail(db, ticket, user_id)
