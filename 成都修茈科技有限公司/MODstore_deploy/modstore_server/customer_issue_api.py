# mypy: disable-error-code="arg-type, assignment"
"""Authenticated, idempotent intake for existing customer defects and private rework."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
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
from modstore_server.work_order_api import route_customer_issue

router = APIRouter()


def _wake_owner_intake(ticket_id: int, source: str) -> None:
    if source == "customer_feedback":
        from modstore_server.customer_service_api import _schedule_customer_ticket_incident

        _schedule_customer_ticket_incident({"ticket_id": int(ticket_id)})


def _route_work_order(
    db: Session, body: CustomerIssueIntakeBody, user: User, ticket: CustomerServiceTicket
) -> None:
    if body.source != "customer_feedback" or not body.work_order_id:
        return
    outcome = route_customer_issue(
        db,
        wo_id=body.work_order_id,
        user=user,
        support_bundle_sha256=body.support_bundle_sha256,
        ticket_id=int(ticket.id),
        ticket_no=str(ticket.ticket_no),
    )
    if not outcome.get("ok"):
        raise HTTPException(409, "客户工单与产品问题 Work Order 不匹配")


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
    work_order_id: str = Field(default="", pattern=r"^$|^WO-[0-9a-f]{12}$")
    support_bundle_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    support_bundle_base64: str = Field(default="", max_length=350_000)
    customer_instance_id: str = Field(default="", max_length=128)
    product_version: str = Field(default="", max_length=64)
    git_sha: str = Field(default="", pattern=r"^$|^[0-9a-f]{40}$")


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
    bundle_b64 = str(values.get("support_bundle_base64") or "")
    bundle_sha = str(values.get("support_bundle_sha256") or "")
    if bool(bundle_b64) != bool(bundle_sha):
        raise HTTPException(400, "support bundle data and SHA256 must be supplied together")
    if bundle_b64:
        try:
            bundle = base64.b64decode(bundle_b64, validate=True)
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                entries = archive.infolist()
                if len(entries) > 500 or sum(item.file_size for item in entries) > 2_000_000:
                    raise ValueError("bundle expands beyond limits")
                if archive.testzip() is not None:
                    raise ValueError("corrupt zip")
        except (ValueError, zipfile.BadZipFile):
            raise HTTPException(400, "support bundle is not a valid ZIP") from None
        if len(bundle) > 256_000 or hashlib.sha256(bundle).hexdigest() != bundle_sha:
            raise HTTPException(400, "support bundle size or SHA256 is invalid")
    stable_values = {
        key: value
        for key, value in values.items()
        if key not in {"support_bundle_sha256", "support_bundle_base64"}
    }
    request_digest = hashlib.sha256(
        json.dumps(stable_values, sort_keys=True, ensure_ascii=False).encode()
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
        payload = response(existing, replayed=True)
        _route_work_order(db, body, user, existing)
        _wake_owner_intake(existing.id, body.source)
        return payload
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
        payload = response(existing, replayed=True)
        _route_work_order(db, body, user, existing)
        _wake_owner_intake(existing.id, body.source)
        return payload
    db.refresh(ticket)
    _route_work_order(db, body, user, ticket)
    _wake_owner_intake(ticket.id, body.source)
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
