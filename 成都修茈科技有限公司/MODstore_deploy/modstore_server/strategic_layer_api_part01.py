# mypy: disable-error-code="misc, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.strategic_layer_api")


def _ledger() -> _facade().StrategicDecisionLedger:
    return _facade().StrategicDecisionLedger()


def _meeting_service() -> _facade().CouncilMeetingService:
    return _facade().CouncilMeetingService()


def _report_service() -> _facade().StrategicReportService:
    return _facade().StrategicReportService()


def _parse_dt(s: _facade().Optional[str]) -> _facade().Optional[_facade().datetime]:
    if not s or not s.strip():
        return None
    try:
        dt = _facade().datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_facade().UTC)
        return dt
    except ValueError as exc:
        raise _facade().HTTPException(400, f"invalid ISO datetime: {s}") from exc


def _to_public_dict(record: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    """将领域记录转为对外字典（屏蔽内部字段）。"""
    if hasattr(record, "to_dict"):
        return record.to_dict()
    if isinstance(record, dict):
        return record
    return {}


def _lifecycle_error_to_http(exc: Exception) -> _facade().HTTPException:
    if isinstance(exc, _facade().DecisionAlreadyDecidedError):
        return _facade().HTTPException(409, str(exc))
    if isinstance(exc, _facade().DecisionLifecycleError):
        return _facade().HTTPException(400, str(exc))
    if isinstance(exc, ValueError):
        return _facade().HTTPException(422, str(exc))
    _facade().logger.exception("strategic layer unexpected error")
    return _facade().HTTPException(500, f"internal error: {exc}")


@_facade().router.get("/council/status", response_model=_facade().Dict[str, _facade().Any])
def get_strategic_council_status(
    limit: int = _facade().Query(20, ge=1, le=100),
    _: _facade().User = _facade().Depends(_facade().get_current_user),
) -> _facade().Dict[str, _facade().Any]:
    """Return only hash-chain-verified council receipts."""
    from modstore_server.strategic_council import strategic_council_status

    return {"ok": True, "data": strategic_council_status(limit=limit)}


@_facade().router.post("/council/review", response_model=_facade().Dict[str, _facade().Any])
def run_strategic_council_review(
    body: _facade().StrategicCouncilReviewRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """Run the three seats against live evidence and append one immutable attempt."""
    from modstore_server.strategic_council import build_live_strategic_council_receipt

    try:
        receipt = build_live_strategic_council_receipt(**body.model_dump())
    except RuntimeError as exc:
        raise _facade().HTTPException(409, str(exc)) from exc
    return {"ok": receipt.get("verified") is True, "receipt": receipt}


class RetortClarificationAnswerRequest(_facade().BaseModel):
    answers: _facade().Any = _facade().Field(
        ..., description="字符串、{question_id: answer} 或 [{id, answer}]"
    )


@_facade().router.get("/council/clarifications", response_model=_facade().Dict[str, _facade().Any])
def list_retort_clarifications(
    include_terminal: bool = _facade().Query(False),
    limit: int = _facade().Query(50, ge=1, le=200),
    _: _facade().User = _facade().Depends(_facade().get_current_user),
) -> _facade().Dict[str, _facade().Any]:
    """List open (or all) Retort clarification sessions after TTL sweep."""
    from modstore_server.retort_clarification_gate import list_clarifications

    return list_clarifications(include_terminal=include_terminal, limit=limit)


@_facade().router.get(
    "/council/clarifications/{session_id}", response_model=_facade().Dict[str, _facade().Any]
)
def get_retort_clarification(
    session_id: str, _: _facade().User = _facade().Depends(_facade().get_current_user)
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.retort_clarification_gate import get_clarification

    row = get_clarification(session_id)
    if not row:
        raise _facade().HTTPException(404, "clarification session not found")
    return {"ok": True, "session": row}


@_facade().router.post(
    "/council/clarifications/{session_id}/answer", response_model=_facade().Dict[str, _facade().Any]
)
def answer_retort_clarification(
    session_id: str,
    body: RetortClarificationAnswerRequest,
    admin: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.retort_clarification_gate import answer_clarification

    out = answer_clarification(
        session_id, answers=body.answers, answered_by=_facade().authenticated_admin_actor(admin)
    )
    if not out.get("ok"):
        raise _facade().HTTPException(409, str(out.get("error") or "answer failed"))
    return out


@_facade().router.post(
    "/council/clarifications/sweep", response_model=_facade().Dict[str, _facade().Any]
)
def sweep_retort_clarifications(
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """Expire stale sessions and prune terminal backlog (anti-pileup)."""
    from modstore_server.retort_clarification_gate import sweep_expired_clarifications

    return sweep_expired_clarifications()


@_facade().router.post("/decisions", response_model=_facade().Dict[str, _facade().Any])
def propose_decision(
    body: _facade().ProposeDecisionRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """提议新决策；服务层立即评估自治边界并决定初始状态。"""
    try:
        decision_type = _facade().DecisionType(body.decision_type)
    except ValueError as exc:
        raise _facade().HTTPException(422, f"invalid decision_type: {body.decision_type}") from exc
    try:
        record = (
            _facade()
            ._ledger()
            .propose(
                title=body.title,
                action=body.action,
                proposer=_facade().DecisionProposer(
                    actor=body.actor, rationale=body.rationale, payload=body.payload
                ),
                decision_type=decision_type,
                scope=body.scope,
                scope_ref=body.scope_ref,
                execution_plan=body.execution_plan,
            )
        )
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.get("/decisions", response_model=_facade().Dict[str, _facade().Any])
def list_decisions(
    status: _facade().Optional[str] = _facade().Query(None, description="按状态过滤"),
    decision_type: _facade().Optional[str] = _facade().Query(None, description="按类型过滤"),
    scope: _facade().Optional[str] = _facade().Query(None, description="按作用域过滤"),
    limit: int = _facade().Query(50, ge=1, le=500),
    _: _facade().User = _facade().Depends(_facade().get_current_user),
) -> _facade().Dict[str, _facade().Any]:
    """列出最近的决策（按 ``proposed_at`` 倒序）。"""
    status_enum: _facade().Optional[_facade().DecisionStatus] = None
    if status:
        try:
            status_enum = _facade().DecisionStatus(status)
        except ValueError as exc:
            raise _facade().HTTPException(422, f"invalid status: {status}") from exc
    type_enum: _facade().Optional[_facade().DecisionType] = None
    if decision_type:
        try:
            type_enum = _facade().DecisionType(decision_type)
        except ValueError as exc:
            raise _facade().HTTPException(422, f"invalid decision_type: {decision_type}") from exc
    records = (
        _facade()
        ._ledger()
        .list_recent(status=status_enum, decision_type=type_enum, scope=scope, limit=limit)
    )
    return {
        "ok": True,
        "count": len(records),
        "items": [_facade()._to_public_dict(r) for r in records],
    }


@_facade().router.get("/decisions/{decision_id}", response_model=_facade().Dict[str, _facade().Any])
def get_decision(
    decision_id: str, _: _facade().User = _facade().Depends(_facade().get_current_user)
) -> _facade().Dict[str, _facade().Any]:
    """查询单条决策详情。"""
    record = _facade()._ledger().get(decision_id)
    if record is None:
        raise _facade().HTTPException(404, f"decision not found: {decision_id}")
    return {"ok": True, "decision": _facade()._to_public_dict(record)}


@_facade().router.post(
    "/decisions/{decision_id}/approve", response_model=_facade().Dict[str, _facade().Any]
)
def approve_decision(
    decision_id: str,
    body: _facade().DecisionReviewRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """人工或会议通过决策（仅 proposed 状态可调用）。"""
    try:
        decided_by = _facade().DecidedBy(body.decided_by)
    except ValueError as exc:
        raise _facade().HTTPException(422, f"invalid decided_by: {body.decided_by}") from exc
    try:
        record = (
            _facade()
            ._ledger()
            .approve(decision_id, decided_by=decided_by, review_notes=body.review_notes)
        )
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.post(
    "/decisions/{decision_id}/reject", response_model=_facade().Dict[str, _facade().Any]
)
def reject_decision(
    decision_id: str,
    body: _facade().DecisionReviewRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """人工或会议否决决策（仅 proposed 状态可调用，review_notes 必填）。"""
    try:
        decided_by = _facade().DecidedBy(body.decided_by)
    except ValueError as exc:
        raise _facade().HTTPException(422, f"invalid decided_by: {body.decided_by}") from exc
    try:
        record = (
            _facade()
            ._ledger()
            .reject(decision_id, decided_by=decided_by, review_notes=body.review_notes)
        )
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.post(
    "/decisions/{decision_id}/withdraw", response_model=_facade().Dict[str, _facade().Any]
)
def withdraw_decision(
    decision_id: str,
    body: _facade().WithdrawRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """撤回决策（任意非终态可调用）。"""
    try:
        record = _facade()._ledger().withdraw(decision_id, actor=body.actor, reason=body.reason)
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.post(
    "/decisions/{decision_id}/start", response_model=_facade().Dict[str, _facade().Any]
)
def start_decision(
    decision_id: str,
    body: _facade().StartExecutionRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """开始执行决策（auto_approved 或 approved 状态可调用）。"""
    try:
        record = (
            _facade()
            ._ledger()
            .start_execution(decision_id, execution_plan=body.execution_plan or None)
        )
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.post(
    "/decisions/{decision_id}/complete", response_model=_facade().Dict[str, _facade().Any]
)
def complete_decision(
    decision_id: str,
    body: _facade().CompleteExecutionRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """执行层回写完成结果（executing 状态可调用）。"""
    review_at = _facade()._parse_dt(body.review_at)
    try:
        record = (
            _facade()
            ._ledger()
            .complete_execution(
                decision_id, execution_result=body.execution_result, review_at=review_at
            )
        )
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.post(
    "/decisions/{decision_id}/review", response_model=_facade().Dict[str, _facade().Any]
)
def review_decision(
    decision_id: str,
    body: _facade().ReviewDecisionRequest,
    _: _facade().User = _facade().Depends(_facade().require_admin),
) -> _facade().Dict[str, _facade().Any]:
    """复盘（completed 状态可调用，仅一次）。"""
    try:
        record = (
            _facade()
            ._ledger()
            .review(decision_id, reviewer=body.reviewer, review_notes=body.review_notes)
        )
        return {"ok": True, "decision": _facade()._to_public_dict(record)}
    except _facade().RECOVERABLE_ERRORS as exc:
        raise _facade()._lifecycle_error_to_http(exc) from exc


@_facade().router.get("/autonomy/rules", response_model=_facade().Dict[str, _facade().Any])
def list_autonomy_rules(
    _: _facade().User = _facade().Depends(_facade().get_current_user),
) -> _facade().Dict[str, _facade().Any]:
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
