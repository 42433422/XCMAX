"""Management controls for one enterprise identity, never a browser-local agent."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import and_, or_, select

from modstore_server.api.deps import require_admin
from modstore_server.db.db_base import get_session_factory
from modstore_server.db.xiaoc_life import XiaoCLifeEvent
from modstore_server.models import User
from modstore_server.strategic_portfolio import (
    Opportunity,
    PortfolioError,
    PortfolioLimits,
    create_portfolio_proposal,
    digest,
)
from modstore_server.xiaoc_goal_governance import governance_gate
from modstore_server.xiaoc_goal_management import (
    ORIGIN,
    GoalStepAllocation,
    build_goal_opportunities,
    check_candidate_promotion,
)
from modstore_server.xiaoc_life_policy import IDENTITY_ID, LifePolicyError, LifeUpdate, utcnow
from modstore_server.xiaoc_life_store import (
    _event,
    _event_dict,
    _mutate,
    manage_operating_goal,
    read_state,
    update_settings,
    wake,
)

router = APIRouter(prefix="/life", tags=["xiaoc-life"])


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)


class ReviewExperience(RevisionBody):
    candidate_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["confirm", "reject", "revoke"]


class ManageGoal(RevisionBody):
    action: Literal["pause", "resume", "cancel", "adjust"]
    reason: str = Field(min_length=1, max_length=500)
    review_note: str | None = Field(default=None, max_length=1000)
    review_deadline: str | None = Field(default=None, max_length=64)


class PromoteGoal(RevisionBody):
    employee_id: str = Field(min_length=1, max_length=128)
    limits: PortfolioLimits
    input_data: dict[str, Any] = Field(default_factory=dict)
    step_allocations: list[GoalStepAllocation] = Field(default_factory=list, max_length=2)

    @field_validator("input_data")
    @classmethod
    def valid_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        from modstore_server.strategic_execution_contract import validate_input

        return validate_input(value)


def _call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except ValidationError as exc:
        raise HTTPException(422, "自主预算配置无效，请检查数值与授权到期时间") from exc
    except (LifePolicyError, PortfolioError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
def get_life(_admin: User = Depends(require_admin)) -> dict[str, Any]:
    return read_state()


@router.get("/self-model")
async def get_self_model(admin: User = Depends(require_admin)) -> dict[str, Any]:
    from modstore_server.xiaoc_self_metrics import (
        audit_projection,
        read_accrual,
        with_cycle_receipts,
    )
    from modstore_server.xiaoc_self_model import (
        execution_scope,
        model_inventory,
        project,
        registry_inventory,
    )

    state = await asyncio.to_thread(read_state)
    state = await asyncio.to_thread(with_cycle_receipts, state)
    result = project(state)
    inventory = await asyncio.to_thread(registry_inventory, state, admin)
    inventory["models"] = await model_inventory()
    result["inventory"] = inventory
    result["inventory_status"] = "point_in_time_registry_not_independent_proof"
    costs = await asyncio.to_thread(read_accrual, state)
    result["performance"]["cost_cents"] = costs["cost_cents"]
    result["performance"]["cost_status"] = costs["status"]
    result["cost_evidence"] = costs
    from modstore_server.xiaoc_self_evidence import annotate_unverified_catalog, fixture_trend

    catalog = await asyncio.to_thread(audit_projection)
    result["audit_catalog"] = annotate_unverified_catalog(
        catalog,
        state.get("self_fixture_checks", []),
        current_sha=result["identity"]["release"]["git_sha"],
    )
    result["fixture_trend"] = fixture_trend(
        state.get("self_fixture_checks", []),
        current_sha=result["identity"]["release"]["git_sha"],
    )
    current = await asyncio.to_thread(read_state)
    if (
        current["revision"] != state["revision"]
        or execution_scope(current) != execution_scope(state)
        or current.get("self_authority_active") != state.get("self_authority_active")
    ):
        raise HTTPException(409, "自我状态已变化，请重新读取")
    return result


@router.put("")
def put_life(body: LifeUpdate, admin: User = Depends(require_admin)) -> dict[str, Any]:
    return cast_state(_call(update_settings, body, actor_user_id=int(admin.id)))


def cast_state(value: Any) -> dict[str, Any]:
    return dict(value)


@router.post("/wake")
def wake_life(body: RevisionBody, admin: User = Depends(require_admin)) -> dict[str, Any]:
    # Only changes the persistent due time. The existing scheduler claims work.
    return cast_state(
        _call(wake, actor_user_id=int(admin.id), expected_revision=body.expected_revision)
    )


@router.get("/experiences")
def experiences(
    query: str = Query("", max_length=200),
    limit: int = Query(30, ge=1, le=100),
    before: str | None = Query(None, max_length=96),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    with get_session_factory()() as session:
        statement = select(XiaoCLifeEvent).where(XiaoCLifeEvent.identity_id == IDENTITY_ID)
        if query.strip():
            statement = statement.where(
                XiaoCLifeEvent.summary.icontains(query.strip(), autoescape=True)
            )
        if before:
            cursor = session.get(XiaoCLifeEvent, before)
            if cursor is None or cursor.identity_id != IDENTITY_ID:
                raise HTTPException(404, "经历游标不存在")
            statement = statement.where(
                or_(
                    XiaoCLifeEvent.created_at < cursor.created_at,
                    and_(
                        XiaoCLifeEvent.created_at == cursor.created_at,
                        XiaoCLifeEvent.id < cursor.id,
                    ),
                )
            )
        rows = session.scalars(
            statement.order_by(XiaoCLifeEvent.created_at.desc(), XiaoCLifeEvent.id.desc()).limit(
                limit
            )
        ).all()
        return {
            "items": [_event_dict(row) for row in rows],
            "next_cursor": rows[-1].id if len(rows) == limit else None,
        }


@router.post("/experiences/{candidate_id}/review")
def review_experience(
    candidate_id: str, body: ReviewExperience, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from modstore_server.xiaoc_life_experience_review import review_experience as apply_review

    return cast_state(
        _call(
            apply_review,
            candidate_id,
            candidate_sha256=body.candidate_sha256,
            action=body.action,
            expected_revision=body.expected_revision,
            actor_user_id=int(admin.id),
        )
    )


@router.post("/goals/{goal_id}/manage")
def manage_goal(
    goal_id: str, body: ManageGoal, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    """Manage only review material; bound jobs remain owned by original portfolio."""
    return cast_state(
        _call(
            manage_operating_goal,
            goal_id,
            action=body.action,
            expected_revision=body.expected_revision,
            actor_user_id=int(admin.id),
            reason=body.reason,
            review_note=body.review_note,
            review_deadline=body.review_deadline,
        )
    )


@router.post("/goals/{goal_id}/portfolio")
def promote_goal(
    goal_id: str, body: PromoteGoal, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    """Turn a sourced finding into the existing reviewable strategic proposal."""
    from modstore_server.task_router import _load_all_employee_profiles

    state = read_state()
    if state["revision"] != body.expected_revision or state.get("owner_user_id") != int(admin.id):
        raise HTTPException(409, "请由当前自主预算授权人读取最新设置后转为企业提案")
    goal = next((item for item in state["goals"] if item["id"] == goal_id), None)
    if goal is None:
        raise HTTPException(404, "目标不存在")
    if goal.get("retort_request_id") and not goal.get("decision_id"):
        raise HTTPException(
            409, "原改进目标须先完成原派工审批，由 L6 循环生成绑定原任务的工程预算提案"
        )
    if goal.get("candidate_origin") == ORIGIN and goal.get("candidate_owner_user_id") != int(
        admin.id
    ):
        raise HTTPException(409, "经营候选不属于当前授权人")
    if goal.get("decision_id"):
        return {"decision_id": goal["decision_id"], "life": state}
    if body.employee_id not in {item.get("id") for item in _load_all_employee_profiles()}:
        raise HTTPException(422, "请选择现有可执行员工")
    if not goal.get("evidence_refs"):
        raise HTTPException(409, "没有实际来源的想法不能转为执行提案")
    limits = body.limits.model_dump()
    if goal.get("candidate_origin") == ORIGIN:
        gate = governance_gate(goal, state["goals"], now=utcnow())
        if gate["status"] != "reviewable":
            raise HTTPException(409, "目标存在冲突或未完成的真实前置条件，禁止转入审批")
        from modstore_server.strategy_business_context import customer_value_context

        _call(
            check_candidate_promotion,
            goal,
            int(admin.id),
            limits,
            customer_value_context(),
            now=utcnow(),
        )
    opportunity = Opportunity(
        opportunity_id="life-" + digest(goal_id)[:24],
        title=goal["title"][:200],
        task=str(goal.get("description") or goal["title"])[:4000],
        employee_id=body.employee_id,
        input_data=body.input_data,
        value_score=100,
        confidence_bps=5000,
        cost_cents=limits["cost_cents"],
        tokens=limits["tokens"],
        compute_seconds=min(limits["compute_seconds"], 240),
        risk="medium",
        source_refs=goal["evidence_refs"][:32],
    )
    step_bindings = {}
    opportunities = [opportunity.model_dump()]
    if body.step_allocations:
        profiles = {item.get("id") for item in _load_all_employee_profiles()}
        if any(row.employee_id not in profiles for row in body.step_allocations):
            raise HTTPException(422, "请选择现有可执行员工")
        opportunities, step_bindings = _call(
            build_goal_opportunities, goal, body.step_allocations, limits
        )
    proposal = _call(
        create_portfolio_proposal,
        owner_user_id=int(admin.id),
        goal=goal["title"],
        period="xiaoc-life:" + goal_id[:45],
        limits=limits,
        opportunities=opportunities,
        idempotency_key="xiaoc-life:"
        + digest(
            [goal_id, ORIGIN]
            if goal.get("candidate_origin") == ORIGIN
            else [goal_id, limits, body.employee_id, body.input_data]
        ),
    )
    decision_id = proposal["decision"]["decision_id"]

    def bind(current: dict[str, Any], session: Any) -> None:
        if current["revision"] != body.expected_revision or current["owner_user_id"] != int(
            admin.id
        ):
            raise LifePolicyError("设置已变化，提案保留待审核，未启动任何任务")
        target = next(item for item in current["goals"] if item["id"] == goal_id)
        if goal.get("candidate_origin") == ORIGIN and (
            target.get("candidate_owner_user_id") != int(admin.id)
            or target.get("observation") != goal.get("observation")
            or (not target.get("decision_id") and target.get("status") != "proposed")
        ):
            raise LifePolicyError("原经营候选已改变，提案未绑定")
        if goal.get("candidate_origin") == ORIGIN and (
            governance_gate(target, current["goals"], now=utcnow())["status"] != "reviewable"
        ):
            raise LifePolicyError("并发状态中的原目标已冲突、过期或来源被更改，禁止绑定")
        if target.get("decision_id") not in (None, "", decision_id):
            raise LifePolicyError("目标已绑定另一个提案")
        if target.get("decision_id") == decision_id:
            return  # A repeated promotion cannot reset an approved or terminal goal.
        target.update(decision_id=decision_id, status="awaiting_approval")
        if step_bindings:
            target.update(
                step_bindings=step_bindings,
                subgoals_status="bound_to_original_portfolio",
            )
        event_id = "portfolio:" + digest([goal_id, decision_id])[:64]
        if session.get(XiaoCLifeEvent, event_id) is None:
            _event(
                session,
                event_id,
                kind="enterprise",
                status="awaiting_approval",
                summary=f"研究目标已转为待批准的企业提案：{target['title']}",
                evidence_refs=[*target["evidence_refs"][:30], f"portfolio:{decision_id}"],
            )

    _call(_mutate, bind)
    return {**proposal, "decision_id": decision_id, "life": read_state()}
