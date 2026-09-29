"""Shared Work Order and customer-intake API."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db, require_admin
from modstore_server.db.work_orders import WorkOrderEvent
from modstore_server.models import User
from modstore_server.work_order_core import (
    WO_TRACKS,
    acceptance_plan,
    classify_track,
    derive_wo_id,
    fold,
    is_valid_wo_id,
    validate_transition,
)

router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])
_CUSTOMER_ROUTABLE_STATES = "routed in_dev merged released verifying closed reopened".split()


class CandidateBody(BaseModel):
    source: str = Field(default="", max_length=64)
    dedup_key: str = Field(..., max_length=96)
    reason: str = Field(default="", max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


class CustomerCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["client_ai_product_issue"] = "client_ai_product_issue"
    dedup_key: str = Field(..., min_length=1, max_length=96)
    reason: Literal["product_defect"] = "product_defect"
    expected: str = Field(..., min_length=1, max_length=1000)
    actual: str = Field(..., min_length=1, max_length=1000)
    confidence: float = Field(..., ge=0.8, le=1)
    support_bundle_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    client_instance_id: str = Field(..., min_length=1, max_length=128)
    product_version: str = Field(..., min_length=1, max_length=64)
    git_sha: str = Field(..., pattern=r"^[0-9a-f]{40}$")
    platform: str = Field(..., min_length=1, max_length=64)


class TransitionBody(BaseModel):
    wo_id: str = Field(..., max_length=32)
    to_state: str = Field(..., max_length=16)
    ref: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="", max_length=500)
    source: str = Field(default="api", max_length=64)


class AcceptanceBody(BaseModel):
    issue_number: int = Field(..., gt=0)
    release_version: str = Field(..., max_length=64)
    verdict: str = Field(..., max_length=16)
    evidence: dict[str, Any] = Field(default_factory=dict)


class GateReceiptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wo_id: str = Field(..., max_length=32)
    gate: str = Field(..., min_length=1, max_length=64)
    gate_status: str = Field(..., min_length=1, max_length=64)
    evidence: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="", max_length=500)
    source: str = Field(default="self_heal_loop", max_length=64)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _append_event(db: Session, *, event: dict[str, Any]) -> None:
    row = WorkOrderEvent(
        wo_id=str(event["wo_id"]),
        event=str(event["event"]),
        source=str(event.get("source") or ""),
        dedup_key=str(event.get("dedup_key") or ""),
        reason=str(event.get("reason") or ""),
        context=json.dumps(event.get("context") or {}, ensure_ascii=False),
        from_state=str(event.get("from_state") or ""),
        to_state=str(event.get("to_state") or ""),
        ref=json.dumps(event.get("ref") or {}, ensure_ascii=False),
        note=str(event.get("note") or "")[:500],
        at=_now_utc(),
        ts_unix=_now_utc().timestamp(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)


def _events_of(db: Session, wo_id: str) -> list[WorkOrderEvent]:
    return (
        db.query(WorkOrderEvent)
        .filter(WorkOrderEvent.wo_id == wo_id)
        .order_by(WorkOrderEvent.id.asc())
        .all()
    )


def _view(db: Session, wo_id: str) -> dict[str, Any] | None:
    if not is_valid_wo_id(wo_id):
        return None
    views = fold(_events_of(db, wo_id))
    return views.get(wo_id)


def _created_facts(db: Session, wo_id: str) -> tuple[str, str, dict[str, Any]]:
    """创建事件的 (reason, source, context)，供 routed 缺省分类。"""
    for rec in _events_of(db, wo_id):
        if str(rec.event) == "created":
            return (
                str(rec.reason or ""),
                str(rec.source or ""),
                _loads(rec.context),
            )
    return "", "", {}


@router.post("/candidate")
def create_candidate(
    body: CandidateBody,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    return _create_candidate(db, body)


def _create_candidate(db: Session, body: CandidateBody) -> dict[str, Any]:
    key = str(body.dedup_key or "").strip()
    if not key:
        return {"wo_id": "", "created": False, "status": "", "reason": "empty_dedup_key"}
    source = str(body.source or "").strip() or "unknown"
    wo_id = derive_wo_id(key)
    existing = _view(db, wo_id)
    if existing:
        return {"wo_id": wo_id, "created": False, "status": existing["status"]}
    _append_event(
        db,
        event={
            "wo_id": wo_id,
            "event": "created",
            "source": source,
            "dedup_key": key,
            "reason": str(body.reason or ""),
            "context": body.context or {},
        },
    )
    return {"wo_id": wo_id, "created": True, "status": "candidate"}


@router.post("/customer-candidate")
def create_customer_candidate(
    body: CustomerCandidateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Allow a logged-in customer to create a candidate, but not route or advance it."""
    context = {
        "customer_user_id": int(user.id),
        "tenant_id": int(user.id),
        "customer_reported": True,
        "expected": body.expected,
        "actual": body.actual,
        "confidence": body.confidence,
        "support_bundle_sha256": body.support_bundle_sha256,
        "client_instance_id": body.client_instance_id,
        "product_version": body.product_version,
        "git_sha": body.git_sha,
        "platform": body.platform,
    }
    scoped_key = hashlib.sha256(str(body.dedup_key).encode()).hexdigest()
    scoped = CandidateBody(
        source=body.source,
        dedup_key=f"customer:{int(user.id)}:{scoped_key}",
        reason=body.reason,
        context=context,
    )
    return _create_candidate(db, scoped)


@router.post("/transition")
def transition(
    body: TransitionBody,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    wo_id = str(body.wo_id or "").strip()
    target = str(body.to_state or "").strip()
    view = _view(db, wo_id)
    if view is None or not is_valid_wo_id(wo_id):
        return {"ok": False, "reason": "unknown_work_order", "wo_id": wo_id}
    current = str(view.get("status") or "")
    invalid = validate_transition(current, target)
    if invalid == "already_in_state":
        return {"ok": True, "reason": "already_in_state", "wo_id": wo_id, "status": current}
    if invalid:
        return {"ok": False, "reason": invalid, "wo_id": wo_id, "status": current}

    ref = dict(body.ref or {})
    if target == "routed":
        track = str(ref.get("track") or "").strip()
        if track and track not in WO_TRACKS:
            return {"ok": False, "reason": "unknown_track", "wo_id": wo_id, "track": track}
        if not track:
            reason, source, context = _created_facts(db, wo_id)
            track = classify_track(source=source, reason=reason, context=context)
        ref["track"] = track

    _append_event(
        db,
        event={
            "wo_id": wo_id,
            "event": "transition",
            "from_state": current,
            "to_state": target,
            "ref": ref,
            "note": str(body.note or "")[:500],
            "source": str(body.source or "api"),
        },
    )
    return {"ok": True, "wo_id": wo_id, "from": current, "to": target}


def route_customer_issue(
    db: Session,
    *,
    wo_id: str,
    user: User,
    support_bundle_sha256: str,
    ticket_id: int | None,
    ticket_no: str = "",
) -> dict[str, Any]:
    view = _view(db, wo_id)
    context = (view or {}).get("context") or {}
    if (
        not view
        or view.get("source") != "client_ai_product_issue"
        or not context.get("customer_reported")
        or int(context.get("customer_user_id") or 0) != int(user.id)
        or not support_bundle_sha256
    ):
        return {"ok": False, "reason": "client_work_order_mismatch", "wo_id": wo_id}
    status = view.get("status")
    if status != "candidate" and status not in _CUSTOMER_ROUTABLE_STATES:
        return {"ok": False, "reason": "work_order_not_routable", "wo_id": wo_id}
    if ticket_id is None:
        return {"ok": True, "wo_id": wo_id}
    if status == "candidate":
        transition(
            TransitionBody(
                wo_id=wo_id,
                to_state="routed",
                ref={
                    "track": "product_line",
                    "customer_ticket_id": ticket_id,
                    "customer_ticket_no": ticket_no,
                },
                source="customer_issue_intake",
            ),
            db=db,
            _user=user,
        )
    history = view.get("history") or []
    receipts = {
        event["ref"]["gate"]: event["ref"]
        for event in history
        if event.get("event") == "gate" and event.get("ref", {}).get("gate")
    }
    for gate, gate_status, evidence in (
        ("intake", "ROUTED", {"customer_ticket_id": ticket_id, "customer_ticket_no": ticket_no}),
        ("evidence", "COLLECTED", {"support_bundle_sha256": support_bundle_sha256}),
    ):
        previous = receipts.get(gate, {})
        if previous.get("gate_status") == gate_status and previous.get("evidence") == evidence:
            continue
        record_gate_receipt(
            GateReceiptBody(wo_id=wo_id, gate=gate, gate_status=gate_status, evidence=evidence),
            db=db,
            _user=user,
        )
    return {"ok": True, "wo_id": wo_id}


@router.post("/gate")
def record_gate_receipt(
    body: GateReceiptBody,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Append a verified gate receipt to the shared Work Order event stream."""
    wo_id = str(body.wo_id or "").strip()
    if not is_valid_wo_id(wo_id) or _view(db, wo_id) is None:
        return {"ok": False, "reason": "unknown_work_order", "wo_id": wo_id}
    evidence_json = json.dumps(body.evidence or {}, ensure_ascii=False, separators=(",", ":"))
    if len(evidence_json.encode("utf-8")) > 16_384:
        return {"ok": False, "reason": "evidence_too_large", "wo_id": wo_id}
    _append_event(
        db,
        event={
            "wo_id": wo_id,
            "event": "gate",
            "source": str(body.source or "self_heal_loop"),
            "ref": {
                "gate": str(body.gate).strip(),
                "gate_status": str(body.gate_status).strip(),
                "evidence": body.evidence or {},
            },
            "note": str(body.note or "")[:500],
        },
    )
    return {
        "ok": True,
        "wo_id": wo_id,
        "gate": str(body.gate).strip(),
        "gate_status": str(body.gate_status).strip(),
    }


@router.post("/acceptance")
def acceptance(
    body: AcceptanceBody,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    issue_number = int(body.issue_number)
    view = _find_by_issue(db, issue_number)
    if view is None:
        return {"ok": False, "reason": "issue_not_linked", "issue_number": issue_number}
    wo_id = str(view["wo_id"])
    current = str(view.get("status") or "")
    plan = acceptance_plan(
        current=current,
        issue_number=issue_number,
        release_version=body.release_version,
        verdict=body.verdict,
        evidence=body.evidence or None,
        seen_version=str(view.get("release_version") or ""),
    )
    target = str(plan.get("target") or "")
    if not plan.get("ok"):
        out: dict[str, Any] = {"ok": False, "wo_id": wo_id, "status": current}
        out.update({k: v for k, v in plan.items() if k not in ("ok", "target")})
        return out
    if not target:
        # already_terminal：幂等成功，不重复写事件
        return {
            "ok": True,
            "reason": plan.get("reason", "already_terminal"),
            "wo_id": wo_id,
            "status": current,
        }
    _append_event(
        db,
        event={
            "wo_id": wo_id,
            "event": "transition",
            "from_state": current,
            "to_state": target,
            "ref": plan.get("ref")
            or {"issue_number": issue_number, "release_version": body.release_version},
            "note": str(plan.get("note") or "验收判定"),
            "source": "acceptance",
        },
    )
    return {"ok": True, "wo_id": wo_id, "from": current, "to": target}


def _find_by_issue(db: Session, issue_number: int) -> dict[str, Any] | None:
    """按 issue 反查：找携带该 issue_number 的 transition 事件所属工单再折叠。"""
    hits = db.query(WorkOrderEvent).filter(WorkOrderEvent.event == "transition").all()
    matched_wo: str | None = None
    for rec in hits:
        ref = _loads(rec.ref)
        if int(ref.get("issue_number") or 0) == int(issue_number):
            matched_wo = str(rec.wo_id)
            break
    if matched_wo is None:
        return None
    return _view(db, matched_wo)


@router.get("/by-issue/{issue_number}")
def by_issue(
    issue_number: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    view = _find_by_issue(db, int(issue_number))
    return view if view is not None else {}


@router.get("")
def list_orders(
    status: str = Query(default="", max_length=16),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    views = fold(db.query(WorkOrderEvent).order_by(WorkOrderEvent.id.asc()).all()).values()
    items = [view for view in views if not status or view["status"] == status]
    items.sort(key=lambda view: str(view.get("updated_at") or ""), reverse=True)
    return {"items": items[:limit], "count": len(items)}


@router.get("/{wo_id}")
def get_order(
    wo_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    view = _view(db, wo_id)
    return view if view is not None else {}


__all__ = ["router"]
