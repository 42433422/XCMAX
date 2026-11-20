"""Authenticated control surface over the existing strategic decision ledger."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from modstore_server.api.actor_identity import authenticated_admin_actor
from modstore_server.api.deps import require_admin
from modstore_server.db.strategic import StrategicDecision
from modstore_server.models import User, get_session_factory
from modstore_server.strategic_portfolio import (
    SCHEMA,
    Opportunity,
    PortfolioError,
    PortfolioLimits,
    portfolio_status,
)

router = APIRouter(prefix="/portfolios", tags=["strategic-portfolio"])


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(min_length=1, max_length=4000)
    limits: PortfolioLimits
    use_llm: bool = True


class ProposalRequest(DiscoverRequest):
    period: str = Field(min_length=1, max_length=64)
    opportunities: list[Opportunity] = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=160)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_notes: str = Field(default="", max_length=4000)


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


def _call(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except PortfolioError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 409, str(exc)) from exc


@router.get("")
def list_portfolios(
    limit: int = Query(50, ge=1, le=100),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    with get_session_factory()() as session:
        ids = session.scalars(
            select(StrategicDecision.decision_id)
            .where(
                StrategicDecision.scope == "strategy_portfolio",
                StrategicDecision.scope_ref.startswith(f"user:{admin.id}:"),
            )
            .order_by(StrategicDecision.created_at.desc())
            .limit(limit)
        ).all()
    return {
        "schema": SCHEMA,
        "items": [
            _call(portfolio_status, decision_id, owner_user_id=int(admin.id)) for decision_id in ids
        ],
    }


@router.post("/discover")
async def discover_opportunities(
    body: DiscoverRequest, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from modstore_server.strategic_portfolio_runtime import discover_portfolio_opportunities

    try:
        return await discover_portfolio_opportunities(
            goal=body.goal,
            limits=body.limits.model_dump(),
            use_llm=body.use_llm,
            owner_user_id=int(admin.id),
        )
    except PortfolioError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("")
def propose_portfolio(
    body: ProposalRequest, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from modstore_server.strategic_portfolio import create_portfolio_proposal

    return _call(
        create_portfolio_proposal,
        owner_user_id=int(admin.id),
        goal=body.goal,
        period=body.period,
        limits=body.limits.model_dump(),
        opportunities=[row.model_dump() for row in body.opportunities],
        idempotency_key=body.idempotency_key,
    )


@router.get("/{decision_id}")
def get_portfolio(decision_id: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
    return _call(portfolio_status, decision_id, owner_user_id=int(admin.id))


@router.post("/{decision_id}/approve")
def approve_portfolio(
    decision_id: str, body: ApprovalRequest, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from modstore_server.strategic_portfolio import authorize_portfolio

    return _call(
        authorize_portfolio,
        decision_id,
        owner_user_id=int(admin.id),
        actor=authenticated_admin_actor(admin),
        **body.model_dump(),
    )


@router.post("/{decision_id}/plan")
def plan_portfolio(decision_id: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
    from modstore_server.strategic_portfolio import plan_portfolio as plan

    return _call(plan, decision_id, owner_user_id=int(admin.id))


@router.post("/{decision_id}/run")
def run_portfolio(decision_id: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
    from modstore_server.strategic_portfolio_runtime import run_portfolio_cycle

    return _call(run_portfolio_cycle, decision_id, owner_user_id=int(admin.id), max_tasks=1)


@router.post("/{decision_id}/review")
def review_portfolio(decision_id: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
    from modstore_server.strategic_portfolio_runtime import review_portfolio as review

    return _call(review, decision_id, owner_user_id=int(admin.id))


@router.post("/{decision_id}/stop")
def stop_portfolio(
    decision_id: str, body: StopRequest, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    from modstore_server.strategic_portfolio import stop_portfolio as stop

    return _call(
        stop,
        decision_id,
        owner_user_id=int(admin.id),
        actor=authenticated_admin_actor(admin),
        reason=body.reason,
    )
