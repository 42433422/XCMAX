"""战略-执行分层机制 — FastAPI 路由。

所有路由挂在 ``/api/xcmax/strategic`` 前缀下，分 4 个子域：
- ``/decisions``        — 战略决策账本（提议/批准/执行/复盘）
- ``/autonomy``         — 自治边界规则查看与 seed
- ``/meetings``         — 员工自治会议生命周期
- ``/reports``          — 周报/月报自动产出

鉴权策略：
- 读取类（GET）使用 ``get_current_user``（任意登录用户可读，确保透明）
- 写入类（POST）使用 ``require_admin``（仅管理员可触发状态变更，符合"信任度边界"）
- 内部 AI 员工通过 service-account token 走 ``require_admin`` 等价路径
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import User
from modstore_server.strategic_layer import (
    AutonomyAction,
    CouncilMeetingService,
    DecidedBy,
    DecisionAlreadyDecidedError,
    DecisionLifecycleError,
    DecisionProposer,
    DecisionStatus,
    DecisionType,
    MeetingDecisionRef,
    MeetingParticipants,
    MeetingStatus,
    MeetingType,
    StrategicDecisionLedger,
    StrategicReportService,
    seed_default_boundaries,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax/strategic", tags=["strategic-layer"])


# ─── Pydantic 请求模型 ─────────────────────────────────────────────────────


class ProposeDecisionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="决策标题")
    action: str = Field(
        ..., min_length=1, max_length=500, description="操作描述（用于自治边界匹配）"
    )
    rationale: str = Field("", max_length=2000, description="提议理由")
    actor: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="提议人 ID（ai-strategist/user/<employee_id>）",
    )
    payload: Dict[str, Any] = Field(default_factory=dict, description="决策附加上下文")
    decision_type: str = Field("operational", description="strategic/tactical/operational")
    scope: str = Field("global", description="global/release_train/module/employee/incident")
    scope_ref: str = Field("", max_length=256, description="关联 ID（模块名/版本号/员工 ID 等）")
    execution_plan: Dict[str, Any] = Field(default_factory=dict, description="执行计划 JSON")


class DecisionReviewRequest(BaseModel):
    decided_by: str = Field("user", description="决策者标识：user/council-vote")
    review_notes: str = Field("", max_length=4000, description="决策备注（reject 必填）")


class WithdrawRequest(BaseModel):
    actor: str = Field(..., min_length=1, max_length=128, description="撤回人 ID")
    reason: str = Field(..., min_length=1, max_length=2000, description="撤回原因")


class StartExecutionRequest(BaseModel):
    execution_plan: Dict[str, Any] = Field(default_factory=dict, description="执行计划更新")


class CompleteExecutionRequest(BaseModel):
    execution_result: Dict[str, Any] = Field(default_factory=dict, description="执行结果 JSON")
    review_at: Optional[str] = Field(None, description="复盘截止时间 ISO 字符串（默认 +7d）")


class ReviewDecisionRequest(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=128, description="复盘人 ID")
    review_notes: str = Field(..., min_length=1, max_length=4000, description="复盘结论")


class ScheduleMeetingRequest(BaseModel):
    meeting_type: str = Field(
        "ad_hoc",
        description="daily_standup/weekly_review/monthly_strategy/ad_hoc/incident_review",
    )
    title: str = Field(..., min_length=1, max_length=200)
    scheduled_at: str = Field(..., description="开始时间 ISO 字符串")
    chair: str = Field("", max_length=128, description="主持人 ID")
    required_participants: List[str] = Field(default_factory=list, description="必需参会人 ID 列表")
    optional_participants: List[str] = Field(default_factory=list, description="可选参会人 ID 列表")
    agenda: str = Field(..., min_length=1, max_length=4000, description="议程（Markdown 文本）")
    context: Dict[str, Any] = Field(default_factory=dict, description="会议上下文")


class ConcludeMeetingRequest(BaseModel):
    minutes_md: str = Field(..., min_length=1, max_length=20000, description="会议纪要 Markdown")
    actor: str = Field("ai-strategist", max_length=128, description="结束人 ID")
    decisions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="会议决议列表，每项含 {decision_id, vote_outcome, vote_summary}",
    )
    action_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="action items 列表，每项含 {description, assigned_to, decision_id, due_at}",
    )


class CancelMeetingRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000, description="取消原因")


class UpdateActionItemRequest(BaseModel):
    status: Optional[str] = Field(
        None, description="pending/in_progress/completed/blocked/cancelled"
    )
    result: Optional[Dict[str, Any]] = Field(None, description="执行结果 JSON")
    block_reason: Optional[str] = Field(None, max_length=2000, description="阻塞原因")
    completed_at: Optional[str] = Field(None, description="完成时间 ISO 字符串")


class GenerateWeeklyReportRequest(BaseModel):
    target_date: Optional[str] = Field(None, description="目标日期 ISO 字符串（默认今天）")
    actor: str = Field("ai-strategist", max_length=128, description="生成人 ID")


class GenerateMonthlyReportRequest(BaseModel):
    year: Optional[int] = Field(None, ge=2020, le=2100, description="年份（默认上个月所在年）")
    month: Optional[int] = Field(None, ge=1, le=12, description="月份（默认上个月）")
    actor: str = Field("ai-strategist", max_length=128, description="生成人 ID")


class StrategicCouncilReviewRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1, max_length=128)
    run_id: str = Field(..., min_length=1, max_length=128)
    package_id: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., min_length=1, max_length=64)
    package_sha256: str = Field(..., min_length=64, max_length=64)
    goal_id: str = Field(..., min_length=1, max_length=128)
    loop_run_id: str = Field(..., min_length=1, max_length=128)
    para_task_id: str = Field(..., min_length=1, max_length=128)
    strategy_intent: str = Field(..., min_length=1, max_length=4000)
    changed_files: List[Any] = Field(default_factory=list)


# ─── 工具函数 ───────────────────────────────────────────────────────────────


def _ledger() -> StrategicDecisionLedger:
    return StrategicDecisionLedger()


def _meeting_service() -> CouncilMeetingService:
    return CouncilMeetingService()


def _report_service() -> StrategicReportService:
    return StrategicReportService()


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise HTTPException(400, f"invalid ISO datetime: {s}") from exc


def _to_public_dict(record: Any) -> Dict[str, Any]:
    """将领域记录转为对外字典（屏蔽内部字段）。"""
    if hasattr(record, "to_dict"):
        return record.to_dict()
    if isinstance(record, dict):
        return record
    return {}


def _lifecycle_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, DecisionAlreadyDecidedError):
        return HTTPException(409, str(exc))
    if isinstance(exc, DecisionLifecycleError):
        return HTTPException(400, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    logger.exception("strategic layer unexpected error")
    return HTTPException(500, f"internal error: {exc}")


# ─── Persy / Para / Retort 战略三席 ────────────────────────────────────────


@router.get("/council/status", response_model=Dict[str, Any])
def get_strategic_council_status(
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return only hash-chain-verified council receipts."""

    from modstore_server.strategic_council import strategic_council_status

    return {"ok": True, "data": strategic_council_status(limit=limit)}


@router.post("/council/review", response_model=Dict[str, Any])
def run_strategic_council_review(
    body: StrategicCouncilReviewRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Run the three seats against live evidence and append one immutable attempt."""

    from modstore_server.strategic_council import build_live_strategic_council_receipt

    try:
        receipt = build_live_strategic_council_receipt(**body.model_dump())
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": receipt.get("verified") is True, "receipt": receipt}


class RetortClarificationAnswerRequest(BaseModel):
    answers: Any = Field(..., description="字符串、{question_id: answer} 或 [{id, answer}]")
    answered_by: str = Field("admin", max_length=128)


@router.get("/council/clarifications", response_model=Dict[str, Any])
def list_retort_clarifications(
    include_terminal: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """List open (or all) Retort clarification sessions after TTL sweep."""

    from modstore_server.retort_clarification_gate import list_clarifications

    return list_clarifications(include_terminal=include_terminal, limit=limit)


@router.get("/council/clarifications/{session_id}", response_model=Dict[str, Any])
def get_retort_clarification(
    session_id: str,
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modstore_server.retort_clarification_gate import get_clarification

    row = get_clarification(session_id)
    if not row:
        raise HTTPException(404, "clarification session not found")
    return {"ok": True, "session": row}


@router.post("/council/clarifications/{session_id}/answer", response_model=Dict[str, Any])
def answer_retort_clarification(
    session_id: str,
    body: RetortClarificationAnswerRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    from modstore_server.retort_clarification_gate import answer_clarification

    out = answer_clarification(
        session_id,
        answers=body.answers,
        answered_by=body.answered_by,
    )
    if not out.get("ok"):
        raise HTTPException(409, str(out.get("error") or "answer failed"))
    return out


@router.post("/council/clarifications/sweep", response_model=Dict[str, Any])
def sweep_retort_clarifications(
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """Expire stale sessions and prune terminal backlog (anti-pileup)."""

    from modstore_server.retort_clarification_gate import sweep_expired_clarifications

    return sweep_expired_clarifications()


# ─── 决策账本路由 ──────────────────────────────────────────────────────────


@router.post("/decisions", response_model=Dict[str, Any])
def propose_decision(
    body: ProposeDecisionRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """提议新决策；服务层立即评估自治边界并决定初始状态。"""
    try:
        decision_type = DecisionType(body.decision_type)
    except ValueError as exc:
        raise HTTPException(422, f"invalid decision_type: {body.decision_type}") from exc

    try:
        record = _ledger().propose(
            title=body.title,
            action=body.action,
            proposer=DecisionProposer(
                actor=body.actor,
                rationale=body.rationale,
                payload=body.payload,
            ),
            decision_type=decision_type,
            scope=body.scope,
            scope_ref=body.scope_ref,
            execution_plan=body.execution_plan,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


@router.get("/decisions", response_model=Dict[str, Any])
def list_decisions(
    status: Optional[str] = Query(None, description="按状态过滤"),
    decision_type: Optional[str] = Query(None, description="按类型过滤"),
    scope: Optional[str] = Query(None, description="按作用域过滤"),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出最近的决策（按 ``proposed_at`` 倒序）。"""
    status_enum: Optional[DecisionStatus] = None
    if status:
        try:
            status_enum = DecisionStatus(status)
        except ValueError as exc:
            raise HTTPException(422, f"invalid status: {status}") from exc

    type_enum: Optional[DecisionType] = None
    if decision_type:
        try:
            type_enum = DecisionType(decision_type)
        except ValueError as exc:
            raise HTTPException(422, f"invalid decision_type: {decision_type}") from exc

    records = _ledger().list_recent(
        status=status_enum,
        decision_type=type_enum,
        scope=scope,
        limit=limit,
    )
    return {
        "ok": True,
        "count": len(records),
        "items": [_to_public_dict(r) for r in records],
    }


@router.get("/decisions/{decision_id}", response_model=Dict[str, Any])
def get_decision(
    decision_id: str,
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询单条决策详情。"""
    record = _ledger().get(decision_id)
    if record is None:
        raise HTTPException(404, f"decision not found: {decision_id}")
    return {"ok": True, "decision": _to_public_dict(record)}


@router.post("/decisions/{decision_id}/approve", response_model=Dict[str, Any])
def approve_decision(
    decision_id: str,
    body: DecisionReviewRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """人工或会议通过决策（仅 proposed 状态可调用）。"""
    try:
        decided_by = DecidedBy(body.decided_by)
    except ValueError as exc:
        raise HTTPException(422, f"invalid decided_by: {body.decided_by}") from exc
    try:
        record = _ledger().approve(
            decision_id,
            decided_by=decided_by,
            review_notes=body.review_notes,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


@router.post("/decisions/{decision_id}/reject", response_model=Dict[str, Any])
def reject_decision(
    decision_id: str,
    body: DecisionReviewRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """人工或会议否决决策（仅 proposed 状态可调用，review_notes 必填）。"""
    try:
        decided_by = DecidedBy(body.decided_by)
    except ValueError as exc:
        raise HTTPException(422, f"invalid decided_by: {body.decided_by}") from exc
    try:
        record = _ledger().reject(
            decision_id,
            decided_by=decided_by,
            review_notes=body.review_notes,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


@router.post("/decisions/{decision_id}/withdraw", response_model=Dict[str, Any])
def withdraw_decision(
    decision_id: str,
    body: WithdrawRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """撤回决策（任意非终态可调用）。"""
    try:
        record = _ledger().withdraw(
            decision_id,
            actor=body.actor,
            reason=body.reason,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


@router.post("/decisions/{decision_id}/start", response_model=Dict[str, Any])
def start_decision(
    decision_id: str,
    body: StartExecutionRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """开始执行决策（auto_approved 或 approved 状态可调用）。"""
    try:
        record = _ledger().start_execution(
            decision_id,
            execution_plan=body.execution_plan or None,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


@router.post("/decisions/{decision_id}/complete", response_model=Dict[str, Any])
def complete_decision(
    decision_id: str,
    body: CompleteExecutionRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """执行层回写完成结果（executing 状态可调用）。"""
    review_at = _parse_dt(body.review_at)
    try:
        record = _ledger().complete_execution(
            decision_id,
            execution_result=body.execution_result,
            review_at=review_at,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


@router.post("/decisions/{decision_id}/review", response_model=Dict[str, Any])
def review_decision(
    decision_id: str,
    body: ReviewDecisionRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """复盘（completed 状态可调用，仅一次）。"""
    try:
        record = _ledger().review(
            decision_id,
            reviewer=body.reviewer,
            review_notes=body.review_notes,
        )
        return {"ok": True, "decision": _to_public_dict(record)}
    except Exception as exc:
        raise _lifecycle_error_to_http(exc) from exc


# ─── 自治边界路由 ──────────────────────────────────────────────────────────


@router.get("/autonomy/rules", response_model=Dict[str, Any])
def list_autonomy_rules(
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出所有自治边界规则（用于透明化 AI 决策边界）。"""
    from modstore_server.strategic_layer.autonomy_boundary import AutonomyEvaluator

    evaluator = AutonomyEvaluator.from_db()
    rules = evaluator.list_rules()
    return {
        "ok": True,
        "count": len(rules),
        "items": [r.to_dict() for r in rules],
        "default_action_on_unmatched": "require_human",
    }


@router.post("/autonomy/seed", response_model=Dict[str, Any])
def seed_autonomy_rules(
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """幂等 seed 默认自治边界规则（13 条）。"""
    try:
        inserted = seed_default_boundaries()
        return {
            "ok": True,
            "inserted": inserted,
            "skipped": 13 - inserted,
            "total_default": 13,
        }
    except Exception as exc:
        logger.exception("seed_default_boundaries failed")
        raise HTTPException(500, f"seed failed: {exc}") from exc


# ─── 员工自治会议路由 ──────────────────────────────────────────────────────


@router.post("/meetings", response_model=Dict[str, Any])
def schedule_meeting(
    body: ScheduleMeetingRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """调度新会议。"""
    try:
        meeting_type = MeetingType(body.meeting_type)
    except ValueError as exc:
        raise HTTPException(422, f"invalid meeting_type: {body.meeting_type}") from exc

    scheduled_at = _parse_dt(body.scheduled_at)
    if scheduled_at is None:
        raise HTTPException(422, "scheduled_at required")

    participants = MeetingParticipants(
        required=body.required_participants,
        optional=body.optional_participants,
        chair=body.chair,
    )

    svc = _meeting_service()
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
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("schedule_meeting failed")
        raise HTTPException(500, f"schedule failed: {exc}") from exc


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
            status_enum = MeetingStatus(status)
        except ValueError as exc:
            raise HTTPException(422, f"invalid status: {status}") from exc

    meetings = _meeting_service().list_recent(status=status_enum, limit=limit)
    return {
        "ok": True,
        "count": len(meetings),
        "items": meetings,
    }


@router.get("/meetings/{meeting_id}", response_model=Dict[str, Any])
def get_meeting(
    meeting_id: str,
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询单条会议详情。"""
    meeting = _meeting_service().get(meeting_id)
    if meeting is None:
        raise HTTPException(404, f"meeting not found: {meeting_id}")
    return {"ok": True, "meeting": meeting}


@router.post("/meetings/{meeting_id}/start", response_model=Dict[str, Any])
def start_meeting(
    meeting_id: str,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """开始会议（SCHEDULED → IN_PROGRESS）。"""
    try:
        meeting = _meeting_service().start(meeting_id)
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("start_meeting failed")
        raise HTTPException(500, f"start failed: {exc}") from exc


@router.post("/meetings/{meeting_id}/conclude", response_model=Dict[str, Any])
def conclude_meeting(
    meeting_id: str,
    body: ConcludeMeetingRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """结束会议 + 决议写入决策账本 + action items 闭环。"""
    # 将 dict 列表转为 MeetingDecisionRef 值对象
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
        except Exception as exc:
            raise HTTPException(422, f"invalid decision ref {d}: {exc}") from exc

    try:
        meeting = _meeting_service().conclude(
            meeting_id,
            minutes_md=body.minutes_md,
            decisions=decision_refs,
            action_items=body.action_items,
            actor=body.actor,
        )
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("conclude_meeting failed")
        raise HTTPException(500, f"conclude failed: {exc}") from exc


@router.post("/meetings/{meeting_id}/cancel", response_model=Dict[str, Any])
def cancel_meeting(
    meeting_id: str,
    body: CancelMeetingRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """取消会议。"""
    try:
        meeting = _meeting_service().cancel(meeting_id, reason=body.reason)
        return {"ok": True, "meeting": meeting}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("cancel_meeting failed")
        raise HTTPException(500, f"cancel failed: {exc}") from exc


# ─── Action Items 路由 ──────────────────────────────────────────────────────


@router.get("/action-items", response_model=Dict[str, Any])
def list_action_items(
    status: Optional[str] = Query(None, description="按状态过滤"),
    assignee: Optional[str] = Query(None, description="按负责人过滤"),
    meeting_id: Optional[str] = Query(None, description="按会议 ID 过滤"),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出 action items（可按状态/负责人/会议过滤）。"""
    items = _meeting_service().list_action_items(
        meeting_id=meeting_id,
        assigned_to=assignee,
        status=status,
        limit=limit,
    )
    return {
        "ok": True,
        "count": len(items),
        "items": items,
    }


@router.post("/action-items/{action_item_id}", response_model=Dict[str, Any])
def update_action_item(
    action_item_id: str,
    body: UpdateActionItemRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """更新 action item（状态/结果/阻塞原因/完成时间）。"""
    completed_at = _parse_dt(body.completed_at)
    try:
        item = _meeting_service().update_action_item(
            action_item_id,
            status=body.status,
            result=body.result,
            block_reason=body.block_reason,
            completed_at=completed_at,
        )
        return {"ok": True, "action_item": item}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("update_action_item failed")
        raise HTTPException(500, f"update failed: {exc}") from exc


# ─── 战略层报告路由 ─────────────────────────────────────────────────────────


def _parse_date(s: Optional[str]):
    if not s or not s.strip():
        return None
    try:
        from datetime import date as _date

        return _date.fromisoformat(s.strip()[:10])
    except ValueError as exc:
        raise HTTPException(400, f"invalid ISO date: {s}") from exc


@router.post("/reports/weekly", response_model=Dict[str, Any])
def generate_weekly_report(
    body: GenerateWeeklyReportRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """触发周报生成（默认本周）。"""
    target_date = _parse_date(body.target_date)
    try:
        report = _report_service().generate_weekly_report(
            target_date=target_date,
            actor=body.actor,
        )
        return {"ok": True, "report": report}
    except Exception as exc:
        logger.exception("generate_weekly_report failed")
        raise HTTPException(500, f"weekly report failed: {exc}") from exc


@router.post("/reports/monthly", response_model=Dict[str, Any])
def generate_monthly_report(
    body: GenerateMonthlyReportRequest,
    _: User = Depends(require_admin),
) -> Dict[str, Any]:
    """触发月报生成（默认上个月）。"""
    try:
        report = _report_service().generate_monthly_report(
            year=body.year,
            month=body.month,
            actor=body.actor,
        )
        return {"ok": True, "report": report}
    except Exception as exc:
        logger.exception("generate_monthly_report failed")
        raise HTTPException(500, f"monthly report failed: {exc}") from exc


@router.get("/reports", response_model=Dict[str, Any])
def list_reports(
    report_type: Optional[str] = Query(None, description="weekly/monthly"),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出已生成的报告。"""
    reports = _report_service().list_reports(
        report_type=report_type,
        limit=limit,
    )
    return {
        "ok": True,
        "count": len(reports),
        "items": reports,
    }


@router.get("/reports/{report_key}", response_model=Dict[str, Any])
def get_report(
    report_key: str,
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """查询单条报告（含 Markdown 正文）。"""
    report = _report_service().get_report(report_key)
    if report is None:
        raise HTTPException(404, f"report not found: {report_key}")
    return {"ok": True, "report": report}


# ─── 健康检查路由 ──────────────────────────────────────────────────────────


@router.get("/health", response_model=Dict[str, Any])
def strategic_layer_health(
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """战略层健康检查（用于 CI smoke 与监控）。"""
    try:
        ledger = _ledger()
        decisions = ledger.list_recent(limit=1)
        action_items = _meeting_service().list_action_items(limit=1)
        reports = _report_service().list_reports(limit=1)
        return {
            "ok": True,
            "component": "strategic-layer",
            "decisions_queryable": True,
            "decisions_sample_count": len(decisions),
            "action_items_queryable": True,
            "action_items_sample_count": len(action_items),
            "reports_queryable": True,
            "reports_sample_count": len(reports),
            "autonomy_actions": [a.value for a in AutonomyAction],
            "decision_statuses": [s.value for s in DecisionStatus],
            "decision_types": [t.value for t in DecisionType],
            "decided_by": [d.value for d in DecidedBy],
            "meeting_statuses": [s.value for s in MeetingStatus],
            "meeting_types": [t.value for t in MeetingType],
        }
    except Exception as exc:
        logger.exception("strategic layer health check failed")
        raise HTTPException(500, f"health check failed: {exc}") from exc
