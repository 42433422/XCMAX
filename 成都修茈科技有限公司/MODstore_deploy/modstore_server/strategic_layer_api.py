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

import importlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modstore_server.api.actor_identity import authenticated_admin_actor
from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.models import User
from modstore_server.strategic_layer_models import (
    CancelMeetingRequest as CancelMeetingRequest,
    CompleteExecutionRequest,
    ConcludeMeetingRequest as ConcludeMeetingRequest,
    DecisionReviewRequest,
    GenerateMonthlyReportRequest as GenerateMonthlyReportRequest,
    GenerateWeeklyReportRequest as GenerateWeeklyReportRequest,
    ProposeDecisionRequest,
    ReviewDecisionRequest,
    ScheduleMeetingRequest as ScheduleMeetingRequest,
    StartExecutionRequest,
    StrategicCouncilReviewRequest,
    UpdateActionItemRequest as UpdateActionItemRequest,
    WithdrawRequest,
)
from modstore_server.strategic_layer import (
    AutonomyAction,
    CouncilMeetingService,
    DecidedBy,
    DecisionAlreadyDecidedError,
    DecisionLifecycleError,
    DecisionProposer,
    DecisionStatus,
    DecisionType,
    MeetingStatus,
    MeetingType,
    StrategicDecisionLedger,
    StrategicReportService,
    seed_default_boundaries,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax/strategic", tags=["strategic-layer"])


# ─── Pydantic 请求模型 ─────────────────────────────────────────────────────


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
    admin: User = Depends(require_admin),
) -> Dict[str, Any]:
    from modstore_server.retort_clarification_gate import answer_clarification

    out = answer_clarification(
        session_id,
        answers=body.answers,
        answered_by=authenticated_admin_actor(admin),
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


_routes_module = importlib.import_module("modstore_server.strategic_layer_meeting_routes")
schedule_meeting = _routes_module.schedule_meeting
list_meetings = _routes_module.list_meetings
get_meeting = _routes_module.get_meeting
start_meeting = _routes_module.start_meeting
conclude_meeting = _routes_module.conclude_meeting
cancel_meeting = _routes_module.cancel_meeting
list_action_items = _routes_module.list_action_items
update_action_item = _routes_module.update_action_item
_parse_date = _routes_module._parse_date
generate_weekly_report = _routes_module.generate_weekly_report
generate_monthly_report = _routes_module.generate_monthly_report
list_reports = _routes_module.list_reports
get_report = _routes_module.get_report
