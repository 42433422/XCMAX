"""Administrator assignment, handling and independent verification for customer tickets."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.customer_service_orchestrator import ticket_payload
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceTicket

router = APIRouter()


class HumanAssignBody(BaseModel):
    assignee_id: int
    reason: str = Field(min_length=4, max_length=2000)


class HumanReasonBody(BaseModel):
    reason: str = Field(min_length=4, max_length=4000)


class HumanResultBody(BaseModel):
    text: str = Field(min_length=4, max_length=4000)
    fault_remains: bool = True


class SensitiveRequestBody(BaseModel):
    change: str = Field(min_length=2, max_length=200)
    reason: str = Field(min_length=4, max_length=2000)


class SensitiveDecisionBody(BaseModel):
    action_id: int
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=4, max_length=2000)


def _human_ticket(db: Session, ticket_id: int):
    ticket = db.get(CustomerServiceTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "原工单不存在")
    return ticket


@router.get("/staff")
async def list_ticket_staff(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rows = db.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).limit(50).all()
    return {
        "items": [{"id": row.id, "username": row.username} for row in rows],
        "viewer_id": user.id,
    }


@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket_handler(
    ticket_id: int,
    body: HumanAssignBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_ticket_human_ops import assign_ticket

    ticket = assign_ticket(
        db, _human_ticket(db, ticket_id), user, body.assignee_id, body.reason.strip()
    )
    return {"ticket": ticket_payload(ticket)}


@router.post("/tickets/{ticket_id}/accept")
async def accept_ticket_handler(
    ticket_id: int,
    body: HumanReasonBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_ticket_human_ops import accept_ticket

    ticket = accept_ticket(db, _human_ticket(db, ticket_id), user, body.reason.strip())
    return {"ticket": ticket_payload(ticket)}


@router.post("/tickets/{ticket_id}/diagnose")
async def diagnose_ticket_handler(
    ticket_id: int,
    body: HumanReasonBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_ticket_human_ops import record_diagnosis

    ticket = record_diagnosis(db, _human_ticket(db, ticket_id), user, body.reason.strip())
    return {"ticket": ticket_payload(ticket)}


@router.post("/tickets/{ticket_id}/sensitive-action")
async def request_ticket_sensitive_action(
    ticket_id: int,
    body: SensitiveRequestBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_ticket_human_ops import request_sensitive_action

    result = request_sensitive_action(
        db, _human_ticket(db, ticket_id), user, body.change.strip(), body.reason.strip()
    )
    return result


@router.post("/tickets/{ticket_id}/sensitive-action/decision")
async def decide_ticket_sensitive_action(
    ticket_id: int,
    body: SensitiveDecisionBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_ticket_human_ops import decide_sensitive_action

    return decide_sensitive_action(
        db,
        _human_ticket(db, ticket_id),
        user,
        body.action_id,
        decision=body.decision,
        reason=body.reason.strip(),
    )


@router.post("/tickets/{ticket_id}/result")
async def submit_ticket_result(
    ticket_id: int,
    body: HumanResultBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from modstore_server.customer_ticket_human_ops import submit_result

    ticket = submit_result(
        db,
        _human_ticket(db, ticket_id),
        user,
        text=body.text.strip(),
        fault_remains=body.fault_remains,
    )
    return {"ticket": ticket_payload(ticket)}
