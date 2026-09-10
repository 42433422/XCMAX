"""工单（Work Order SSOT）共享宿主 API：多进程可写同一状态机。

让 FHD 侧本地 JSONL 不再是唯一落点——本地 relay 建 issue、CI closeout 回写验收、
管理端查看，都经本 API 落到共享库 ``work_order_events``。

端点（管理员）：
  POST /api/work-orders/candidate      候选升级唯一工单（幂等）
  POST /api/work-orders/transition     状态迁移（非法迁移拒绝；routed 强制携带轨道）
  POST /api/work-orders/acceptance     验收判定落库（verifying → closed/reopened）
  GET  /api/work-orders/by-issue/{issue_number}
  GET  /api/work-orders/{wo_id}
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
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


class CandidateBody(BaseModel):
    source: str = Field(default="", max_length=64)
    dedup_key: str = Field(..., max_length=96)
    reason: str = Field(default="", max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


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
    key = str(body.dedup_key or "").strip()
    if not key:
        return {"wo_id": "", "created": False, "status": "", "reason": "empty_dedup_key"}
    source = str(body.source or "").strip() or "unknown"
    wo_id = derive_wo_id(source, key)
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


@router.get("/{wo_id}")
def get_order(
    wo_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
) -> dict[str, Any]:
    view = _view(db, wo_id)
    return view if view is not None else {}


__all__ = ["router"]
