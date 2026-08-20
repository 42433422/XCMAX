"""Meeting, action-item, and report routes for the strategic-layer API."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Optional

from fastapi import Depends, Query

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.strategic_layer import (
    MeetingDecisionRef,
    MeetingParticipants,
    MeetingStatus,
)
from modstore_server.strategic_layer_models import (
    CancelMeetingRequest,
    ConcludeMeetingRequest,
    GenerateMonthlyReportRequest,
    GenerateWeeklyReportRequest,
    ScheduleMeetingRequest,
    UpdateActionItemRequest,
)

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["modstore_server.strategic_layer_api"]


router = _facade().router


@router.post("/meetings", response_model=Dict[str, Any])
def schedule_meeting(
    body: ScheduleMeetingRequest, _: User = Depends(require_admin)
) -> Dict[str, Any]:
    """调度新会议。"""
    try:
        meeting_type = _facade().MeetingType(body.meeting_type)
    except ValueError as exc:
        raise _facade().HTTPException(422, f"invalid meeting_type: {body.meeting_type}") from exc
    scheduled_at = _facade()._parse_dt(body.scheduled_at)
    if scheduled_at is None:
        raise _facade().HTTPException(422, "scheduled_at required")
    participants = MeetingParticipants(
        required=body.required_participants,
        optional=body.optional_participants,
        chair=body.chair,
    )
    svc = _facade()._meeting_service()
    try:
        meeting_id = svc.schedule(
            meeting_type=meeting_type,
            title=body.title,
            agenda=body.agenda,
            participants=participants,
            scheduled_at=scheduled_at,
            source_context=body.context or None,
        )
        meeting = svc.get(meeting_id)
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise _facade().HTTPException(422, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("schedule_meeting failed")
        raise _facade().HTTPException(500, f"schedule failed: {exc}") from exc


@router.get("/meetings", response_model=Dict[str, Any])
def list_meetings(
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出最近的会议。"""
    status_enum: Optional[MeetingStatus] = None
    if status:
        try:
            status_enum = _facade().MeetingStatus(status)
        except ValueError as exc:
            raise _facade().HTTPException(422, f"invalid status: {status}") from exc
    meetings = _facade()._meeting_service().list_recent(status=status_enum, limit=limit)
    return {"ok": True, "count": len(meetings), "items": meetings}


@router.get("/meetings/{meeting_id}", response_model=Dict[str, Any])
def get_meeting(meeting_id: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """查询单条会议详情。"""
    meeting = _facade()._meeting_service().get(meeting_id)
    if meeting is None:
        raise _facade().HTTPException(404, f"meeting not found: {meeting_id}")
    return {"ok": True, "meeting": meeting}


@router.post("/meetings/{meeting_id}/start", response_model=Dict[str, Any])
def start_meeting(meeting_id: str, _: User = Depends(require_admin)) -> Dict[str, Any]:
    """开始会议（SCHEDULED → IN_PROGRESS）。"""
    try:
        meeting = _facade()._meeting_service().start(meeting_id)
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("start_meeting failed")
        raise _facade().HTTPException(500, f"start failed: {exc}") from exc


@router.post("/meetings/{meeting_id}/conclude", response_model=Dict[str, Any])
def conclude_meeting(
    meeting_id: str, body: ConcludeMeetingRequest, _: User = Depends(require_admin)
) -> Dict[str, Any]:
    """结束会议 + 决议写入决策账本 + action items 闭环。"""
    decision_refs: List[MeetingDecisionRef] = []
    for d in body.decisions:
        try:
            decision_refs.append(
                MeetingDecisionRef(
                    decision_id=str(d.get("decision_id") or ""),
                    vote_outcome=str(d.get("vote_outcome") or ""),
                    vote_summary=dict(d.get("vote_summary") or {}),
                )
            )
        except RECOVERABLE_ERRORS as exc:
            raise _facade().HTTPException(422, f"invalid decision ref {d}: {exc}") from exc
    try:
        meeting = (
            _facade()
            ._meeting_service()
            .conclude(
                meeting_id,
                minutes_md=body.minutes_md,
                decisions=decision_refs,
                action_items=body.action_items,
                actor=body.actor,
            )
        )
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("conclude_meeting failed")
        raise _facade().HTTPException(500, f"conclude failed: {exc}") from exc


@router.post("/meetings/{meeting_id}/cancel", response_model=Dict[str, Any])
def cancel_meeting(
    meeting_id: str, body: CancelMeetingRequest, _: User = Depends(require_admin)
) -> Dict[str, Any]:
    """取消会议。"""
    try:
        meeting = _facade()._meeting_service().cancel(meeting_id, reason=body.reason)
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("cancel_meeting failed")
        raise _facade().HTTPException(500, f"cancel failed: {exc}") from exc


@router.get("/action-items", response_model=Dict[str, Any])
def list_action_items(
    status: Optional[str] = Query(None, description="按状态过滤"),
    assignee: Optional[str] = Query(None, description="按负责人过滤"),
    meeting_id: Optional[str] = Query(None, description="按会议 ID 过滤"),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出 action items（可按状态/负责人/会议过滤）。"""
    items = (
        _facade()
        ._meeting_service()
        .list_action_items(meeting_id=meeting_id, assigned_to=assignee, status=status, limit=limit)
    )
    return {"ok": True, "count": len(items), "items": items}


@router.post("/action-items/{action_item_id}", response_model=Dict[str, Any])
def update_action_item(
    action_item_id: str, body: UpdateActionItemRequest, _: User = Depends(require_admin)
) -> Dict[str, Any]:
    """更新 action item（状态/结果/阻塞原因/完成时间）。"""
    completed_at = _facade()._parse_dt(body.completed_at)
    try:
        item = (
            _facade()
            ._meeting_service()
            .update_action_item(
                action_item_id,
                status=body.status,
                result=body.result,
                block_reason=body.block_reason,
                completed_at=completed_at,
            )
        )
        return {"ok": True, "action_item": item}
    except ValueError as exc:
        raise _facade().HTTPException(400, str(exc)) from exc
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("update_action_item failed")
        raise _facade().HTTPException(500, f"update failed: {exc}") from exc


def _parse_date(s: Optional[str]):
    if not s or not s.strip():
        return None
    try:
        from datetime import date as _date

        return _date.fromisoformat(s.strip()[:10])
    except ValueError as exc:
        raise _facade().HTTPException(400, f"invalid ISO date: {s}") from exc


@router.post("/reports/weekly", response_model=Dict[str, Any])
def generate_weekly_report(
    body: GenerateWeeklyReportRequest, _: User = Depends(require_admin)
) -> Dict[str, Any]:
    """触发周报生成（默认本周）。"""
    target_date = _facade()._parse_date(body.target_date)
    try:
        report = (
            _facade()
            ._report_service()
            .generate_weekly_report(target_date=target_date, actor=body.actor)
        )
        return {"ok": True, "report": report}
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("generate_weekly_report failed")
        raise _facade().HTTPException(500, f"weekly report failed: {exc}") from exc


@router.post("/reports/monthly", response_model=Dict[str, Any])
def generate_monthly_report(
    body: GenerateMonthlyReportRequest, _: User = Depends(require_admin)
) -> Dict[str, Any]:
    """触发月报生成（默认上个月）。"""
    try:
        report = (
            _facade()
            ._report_service()
            .generate_monthly_report(year=body.year, month=body.month, actor=body.actor)
        )
        return {"ok": True, "report": report}
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("generate_monthly_report failed")
        raise _facade().HTTPException(500, f"monthly report failed: {exc}") from exc


@router.get("/reports", response_model=Dict[str, Any])
def list_reports(
    report_type: Optional[str] = Query(None, description="weekly/monthly"),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出已生成的报告。"""
    reports = _facade()._report_service().list_reports(report_type=report_type, limit=limit)
    return {"ok": True, "count": len(reports), "items": reports}


@router.get("/reports/{report_key}", response_model=Dict[str, Any])
def get_report(report_key: str, _: User = Depends(get_current_user)) -> Dict[str, Any]:
    """查询单条报告（含 Markdown 正文）。"""
    report = _facade()._report_service().get_report(report_key)
    if report is None:
        raise _facade().HTTPException(404, f"report not found: {report_key}")
    return {"ok": True, "report": report}
