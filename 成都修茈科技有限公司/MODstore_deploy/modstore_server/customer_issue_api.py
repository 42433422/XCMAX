# mypy: disable-error-code="arg-type, assignment"
"""Authenticated, idempotent intake for existing customer defects and private rework."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_issue_intake import enqueue_issue, request_identity
from modstore_server.customer_service_orchestrator import (
    ticket_lifecycle_payload,
    ticket_payload,
)
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.models import User, UserMod
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)
from modstore_server.work_order_api import record_customer_decision, route_customer_issue

router = APIRouter()
_CLOSED = frozenset({"resolved", "closed", "done", "rejected"})


def _wake_owner_intake(ticket_id: int, source: str) -> None:
    if source in {"customer_feedback", "customer_reopen"}:
        from modstore_server.customer_service_api import _schedule_customer_ticket_incident

        _schedule_customer_ticket_incident({"ticket_id": int(ticket_id)})


def _route_work_order(
    db: Session,
    body: CustomerIssueIntakeBody,
    user: User,
    ticket: CustomerServiceTicket | None = None,
) -> None:
    if body.source != "customer_feedback" or not body.work_order_id:
        return
    outcome = route_customer_issue(
        db,
        wo_id=body.work_order_id,
        user=user,
        support_bundle_sha256=body.support_bundle_sha256,
        ticket_id=int(ticket.id) if ticket else None,
        ticket_no=str(ticket.ticket_no) if ticket else "",
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
    _route_work_order(db, body, user)
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
        previous = str(ticket.evidence_json)
        evidence = json_loads(previous, {})
        context_keys = {
            "support_bundle_sha256",
            "support_bundle_base64",
            "customer_instance_id",
            "product_version",
            "git_sha",
            "installed_version",
        }
        same_issue = (
            body.source == "customer_feedback"
            and bool(body.work_order_id)
            and all(
                evidence.get(key, "") == value
                for key, value in values.items()
                if key not in context_keys
            )
        )
        if evidence.get("intake_request_sha256") != request_digest and not same_issue:
            raise HTTPException(409, "相同需求标识已绑定其他内容，请使用新的 source_ref")
        report = {key: values[key] for key in context_keys}
        reports = evidence.get("support_reports", [])
        saved = report == {key: evidence.get(key, "") for key in context_keys} or any(
            all(item.get(key, "") == value for key, value in report.items()) for item in reports
        )
        if replayed and bundle_b64 and same_issue and not saved:
            if ticket.status in _CLOSED:
                raise HTTPException(409, "原工单已关闭，请先通过客户复验入口重开")
            revision = hashlib.sha256(json_dumps(report).encode()).hexdigest()
            evidence["support_reports"] = [
                *reports,
                {**report, "received_at": datetime.now(UTC).isoformat()},
            ]
            changed = (
                db.query(CustomerServiceTicket)
                .filter_by(id=ticket.id, user_id=int(user.id), evidence_json=previous)
                .update({"evidence_json": json_dumps(evidence)}, synchronize_session=False)
            )
            if changed != 1:
                db.rollback()
                raise HTTPException(409, "工单已有并发补报，请重试同一请求")
            db.refresh(ticket)
            event_id = enqueue_issue(db, ticket, revision=revision, support_report=report)
            audit(
                db,
                event_type="issue_support_report",
                ticket_id=ticket.id,
                session_id=ticket.session_id,
                actor=user,
                detail={"support_bundle_sha256": bundle_sha, "event_id": event_id},
            )
            db.commit()
            db.refresh(ticket)
            saved = True
        return {
            "success": True,
            "replayed": replayed,
            "ticket_id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "ticket": ticket_payload(ticket),
            "dispatch_status": "queued",
            "support_bundle_saved": bool(bundle_b64) and saved,
            "support_bundle_sha256": bundle_sha if bundle_b64 and saved else "",
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


class CustomerIssueDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["resolved", "reopen"]
    note: str = Field(min_length=4, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


def _issue_row(row: CustomerServiceTicket) -> dict[str, Any]:
    evidence = json_loads(row.evidence_json, {})
    resolution = evidence.get("resolution") or {}
    state = str(resolution.get("state") or "received")
    reports = [r for r in evidence.get("employee_reports") or [] if isinstance(r, dict)]
    closed = row.status in _CLOSED
    return {
        "id": row.id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "summary": row.summary,
        "status": row.status,
        "state": state,
        "lifecycle_label": ticket_lifecycle_payload(row.status, row.decision_status)[
            "lifecycle_label"
        ],
        "latest_result": (
            {k: reports[-1].get(k) for k in ("team_ok", "progress", "at")} if reports else None
        ),
        "last_error": str(resolution.get("last_error") or ""),
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
        "reopen_count": len(evidence.get("reopen_history") or []),
        "can_resolve": not closed,
        "can_reopen": closed or state not in {"received", "reopened"},
    }


@router.get("/issues/mine")
def my_product_issues(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    rows = (
        db.query(CustomerServiceTicket)
        .filter_by(user_id=int(user.id), intent="product_issue")
        .order_by(CustomerServiceTicket.id.desc())
        .limit(30)
        .all()
    )
    return {"items": [_issue_row(row) for row in rows]}


@router.post("/issues/{ticket_id}/decision")
def decide_product_issue(
    ticket_id: int,
    body: CustomerIssueDecisionBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Only the ticket owner closes or reopens; AI results never close a product issue."""
    ticket = (
        db.query(CustomerServiceTicket)
        .filter_by(id=ticket_id, user_id=int(user.id), intent="product_issue")
        .first()
    )
    if ticket is None:
        raise HTTPException(404, "原工单不存在")
    note = body.note.strip()
    if len(note) < 4:
        raise HTTPException(400, "请说明原问题现在的使用结果（至少4个字）")
    evidence = json_loads(ticket.evidence_json, {})
    digest = hashlib.sha256(json.dumps([body.decision, note]).encode()).hexdigest()
    decisions = [r for r in evidence.get("customer_decisions") or [] if isinstance(r, dict)]
    prior = next((r for r in decisions if r.get("idempotency_key") == body.idempotency_key), None)
    if prior:
        if prior.get("request_sha256") != digest:
            raise HTTPException(409, "同一操作标识不可绑定不同内容")
        return {"success": True, "replayed": True, "issue": _issue_row(ticket)}
    resolution = issue_resolution(ticket, evidence)
    closed = ticket.status in _CLOSED
    now = datetime.now(UTC)
    event_id = ""
    if body.decision == "resolved":
        if closed:
            raise HTTPException(409, "工单已关闭；如问题仍存在，请重新打开")
        ticket.status, ticket.decision_status, ticket.closed_at = "resolved", "approved", now
        resolution.update(
            state="resolved",
            resolved_at=now.isoformat(),
            verification_mode="customer_decision",
            closed_by_user_id=int(user.id),
            handled_by=sorted(
                {
                    str(r["employee_id"])
                    for r in resolution.get("team") or []
                    if isinstance(r, dict) and r.get("employee_id")
                }
            ),
        )
    else:
        if not closed and resolution.get("state") in {"received", "reopened"}:
            raise HTTPException(409, "工单仍在处理中，请等处理结果出来后再决定")
        history = [r for r in evidence.get("reopen_history") or [] if isinstance(r, dict)]
        evidence["reopen_history"] = [
            *history,
            {
                "at": now.isoformat(),
                "note": note,
                "previous_status": ticket.status,
                "previous_state": resolution.get("state"),
                "release_target": resolution.pop("release_target", None),
            },
        ]
        for key in ("resolved_at", "verification_mode", "closed_by_user_id", "handled_by"):
            resolution.pop(key, None)
        resolution.update(
            state="reopened",
            repair_verified=False,
            reopen_note=note,
            reopened_at=now.isoformat(),
            reopen_after_action_id=int(
                db.query(func.max(CustomerServiceAction.id))
                .filter(CustomerServiceAction.ticket_id == ticket.id)
                .scalar()
                or 0
            ),
        )
        ticket.status, ticket.decision_status, ticket.closed_at = "processing", "accepted", None
    evidence["resolution"] = resolution
    evidence["customer_decisions"] = [
        *decisions,
        {
            "idempotency_key": body.idempotency_key,
            "decision": body.decision,
            "request_sha256": digest,
            "user_id": int(user.id),
            "at": now.isoformat(),
        },
    ][-50:]
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = now
    db.add(
        CustomerServiceMessage(
            session_id=ticket.session_id,
            ticket_id=ticket.id,
            user_id=int(user.id),
            role="user",
            content=note,
            payload_json=json_dumps({"customer_decision": body.decision}),
        )
    )
    if body.decision == "reopen":
        reopen = len(evidence["reopen_history"])
        event_id = enqueue_issue(db, ticket, revision=f"reopen:{reopen}")
    audit(
        db,
        event_type=f"customer_issue_{body.decision}",
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        actor=user,
        detail={"note": note, "idempotency_key": body.idempotency_key, "event_id": event_id},
    )
    db.commit()
    if evidence.get("work_order_id"):
        record_customer_decision(
            db,
            wo_id=str(evidence["work_order_id"]),
            user=user,
            decision=body.decision,
            ticket_id=int(ticket.id),
        )
    if event_id:
        _wake_owner_intake(ticket.id, "customer_reopen")
    db.refresh(ticket)
    return {"success": True, "replayed": False, "issue": _issue_row(ticket)}
