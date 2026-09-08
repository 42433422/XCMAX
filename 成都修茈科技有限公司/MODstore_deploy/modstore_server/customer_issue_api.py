# mypy: disable-error-code="arg-type, assignment"
"""Authenticated, idempotent intake for existing customer defects and private rework."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_issue_intake import enqueue_issue, request_identity
from modstore_server.customer_service_orchestrator import ticket_payload
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.models import User, UserMod
from modstore_server.models_cs import (
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)

router = APIRouter()


class CustomerIssueIntakeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["private_mod_rework", "enterprise_portal", "customer_feedback"]
    source_ref: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=2, max_length=256)
    description: str = Field(min_length=4, max_length=8000)
    issue_domain: Literal["platform", "software", "custom"] = "platform"
    target_mod_id: str = Field(default="", max_length=128)
    installed_version: str = Field(default="", max_length=64)
    acceptance_criteria: str = Field(default="", max_length=6000)
    shared_core_prerequisite: str = Field(default="", max_length=2000)


@router.post("/issues/intake")
async def intake_customer_issue(
    body: CustomerIssueIntakeBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if body.target_mod_id or body.issue_domain == "custom" or body.source == "private_mod_rework":
        if (
            not body.target_mod_id
            or not db.query(UserMod)
            .filter_by(user_id=int(user.id), mod_id=body.target_mod_id)
            .first()
        ):
            raise HTTPException(403, "当前账号未授权该客户私有 Mod")
    values = body.model_dump()
    request_digest = hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if body.target_mod_id:
        # Runtime identity is trusted source configuration; the caller supplies
        # only the entitlement identity already checked against UserMod above.
        catalog = Path(__file__).resolve().parents[3] / "FHD/config/customer_delivery.json"
        if catalog.is_file():
            deliveries = json.loads(catalog.read_text(encoding="utf-8")).get("deliveries", [])
            delivery: dict[str, Any] = next(
                (row for row in deliveries if row.get("legacy_mod_id") == body.target_mod_id),
                {},
            )
            values["runtime_mod_id"] = str(delivery.get("runtime_mod_id") or body.target_mod_id)
    if body.source == "private_mod_rework":
        values["issue_domain"] = "custom"
    number = request_identity(int(user.id), body.source, body.source_ref)

    def response(ticket: CustomerServiceTicket, *, replayed: bool) -> dict[str, Any]:
        evidence = json_loads(ticket.evidence_json, {})
        if evidence.get("intake_request_sha256") != request_digest:
            raise HTTPException(409, "相同需求标识已绑定其他内容，请使用新的 source_ref")
        return {
            "success": True,
            "replayed": replayed,
            "ticket_id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "ticket": ticket_payload(ticket),
            "dispatch_status": "queued",
        }

    existing = (
        db.query(CustomerServiceTicket).filter_by(ticket_no=number, user_id=int(user.id)).first()
    )
    if existing:
        return response(existing, replayed=True)
    private_rework = body.source == "private_mod_rework"
    intent = "custom_delivery" if private_rework else "product_issue"
    if private_rework:
        values.update(
            kind="module",
            title=body.title,
            requirements=body.description,
            suggested_id=values.get("runtime_mod_id") or body.target_mod_id,
            delivery_managed_by="custom_delivery",
            acceptance_status="pending",
            delivery_terms={"pricing_mode": "initial_included"},
            runs=[],
        )
    session = CustomerServiceSession(
        user_id=int(user.id),
        channel="customer_issue_intake",
        status="open",
        title=body.title,
        intent=intent,
        last_message=body.description,
        context_json=json_dumps({"source": body.source, "source_ref": body.source_ref}),
    )
    db.add(session)
    db.flush()
    ticket = CustomerServiceTicket(
        session_id=session.id,
        user_id=int(user.id),
        ticket_no=number,
        title=body.title,
        intent=intent,
        subject_type="mod" if body.target_mod_id else "host",
        subject_id=body.target_mod_id,
        status="processing",
        decision_status="accepted",
        summary=body.description,
        evidence_json=json_dumps({**values, "intake_request_sha256": request_digest}),
    )
    db.add(ticket)
    try:
        db.flush()
        db.add(
            CustomerServiceMessage(
                session_id=session.id,
                ticket_id=ticket.id,
                user_id=int(user.id),
                role="user",
                content=body.description,
                payload_json="{}",
            )
        )
        event_id = enqueue_issue(db, ticket, revision=request_digest[:24])
        audit(
            db,
            event_type="issue_intake",
            ticket_id=ticket.id,
            session_id=session.id,
            actor=user,
            detail={"source_ref": body.source_ref, "event_id": event_id},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(CustomerServiceTicket)
            .filter_by(ticket_no=number, user_id=int(user.id))
            .first()
        )
        if not existing:
            raise
        return response(existing, replayed=True)
    db.refresh(ticket)
    return response(ticket, replayed=False)


class SharedRuntimeReceiptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: str = Field(min_length=1, max_length=128)
    client_instance_id: str = Field(min_length=1, max_length=128)
    host_sha: str = Field(pattern="^[0-9a-f]{40}$")
    version: str = Field(min_length=1, max_length=64)
    release_id: str = Field(min_length=1, max_length=128)
    signed_metadata_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    case_id: str = Field(min_length=1, max_length=160)
    customer_confirmed: bool = False
    confirmation_note: str = Field(default="", max_length=4000)


@router.get("/issues/pending-runtime")
def pending_issue_runtime(
    host_sha: str = Query(pattern="^[0-9a-f]{40}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from modstore_server.customer_issue_shared_release import bind_shared_release

    rows = (
        db.query(CustomerServiceTicket)
        .filter_by(user_id=int(user.id), status="processing")
        .filter(CustomerServiceTicket.intent.in_(["product_issue", "custom_delivery"]))
        .order_by(CustomerServiceTicket.id.desc())
        .limit(50)
        .all()
    )
    items = []
    for row in rows:
        target = bind_shared_release(db, row, host_sha)
        evidence = json_loads(row.evidence_json, {})
        resolution = evidence.get("resolution") or {}
        if resolution.get("route") != "shared_core":
            continue
        items.append(
            {
                "id": row.id,
                "ticket_no": row.ticket_no,
                "summary": row.summary,
                "state": resolution.get("state"),
                "verification_mode": "customer_confirmation",
                "expected_host_sha": (target or {}).get("host_sha", ""),
                "expected_case_id": (target or {}).get("case_id", ""),
                "target": target,
                "ready": bool(target),
            }
        )
    db.commit()
    return {"items": items}


@router.post("/issues/{ticket_id}/runtime-receipt")
def shared_issue_runtime_receipt(
    ticket_id: int,
    body: SharedRuntimeReceiptBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from modstore_server.customer_issue_shared_release import record_shared_runtime

    ticket = db.query(CustomerServiceTicket).filter_by(id=ticket_id, user_id=int(user.id)).first()
    if ticket is None:
        raise HTTPException(404, "原工单不存在")
    outcome = record_shared_runtime(db, ticket, body.model_dump(), int(user.id))
    db.commit()
    return {"success": True, "ticket": ticket_payload(ticket), "receipt": outcome}
