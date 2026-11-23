"""Approved strategic portfolios: OR-Tools selection and existing SQL ledgers.

CP-SAT owns optimization. SQLAlchemy compare-and-swap owns admission. Prices
are approved CNY tariffs, and realized revenue comes only from payment sources.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from graphlib import TopologicalSorter
from typing import Any, Callable, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError

from modstore_server.db.db_base import get_session_factory
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.strategic_customer_outcomes import CustomerGoalBinding
from modstore_server.strategic_layer import (
    AutonomyEvaluator,
    DecisionProposer,
    DecisionType,
    StrategicDecisionLedger,
)
from modstore_server.strategy_bets import BetHypothesis

SCHEMA = "xcagi.strategic_portfolio/v1"
RESOURCES = ("cost_cents", "tokens", "compute_seconds")
COMPANY_MAX_CANDIDATES = 256
T = TypeVar("T")


class PortfolioError(ValueError):
    """Invalid, unapproved, exhausted or conflicting portfolio operation."""


class ModelTariff(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=256)
    input_cents_per_million: int = Field(ge=0, le=100_000_000)
    output_cents_per_million: int = Field(ge=0, le=100_000_000)
    source: str = Field(min_length=1, max_length=512)


class PortfolioLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    company_budget_id: str = Field(default="", max_length=64)
    cost_cents: int = Field(ge=0, le=100_000_000)
    tokens: int = Field(ge=0, le=1_000_000_000)
    compute_seconds: int = Field(ge=1, le=7_776_000)
    max_parallel: int = Field(default=1, ge=1, le=16)
    max_failures: int = Field(default=2, ge=1, le=128)
    stop_loss_cents: int = Field(ge=0, le=100_000_000)
    min_roi_bps: int = Field(default=0, ge=-10_000, le=1_000_000)
    observation_hours: int = Field(default=168, ge=1, le=2160)
    expires_at: str = Field(min_length=20, max_length=40)
    tariffs: list[ModelTariff] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def valid_limits(self) -> PortfolioLimits:
        _date(self.expires_at)
        if self.stop_loss_cents > self.cost_cents:
            raise ValueError("stop loss cannot exceed the authorized monetary budget")
        routes = [(row.provider, row.model) for row in self.tariffs]
        if len(set(routes)) != len(routes):
            raise ValueError("duplicate model tariffs")
        return self


class Opportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    opportunity_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,96}$")
    title: str = Field(min_length=1, max_length=200)
    task: str = Field(min_length=1, max_length=4000)
    employee_id: str = Field(min_length=1, max_length=128)
    value_score: int = Field(ge=0, le=100_000)
    confidence_bps: int = Field(default=5000, ge=0, le=10_000)
    cost_cents: int = Field(ge=0, le=100_000_000)
    tokens: int = Field(ge=0, le=1_000_000_000)
    compute_seconds: int = Field(ge=1, le=7_776_000)
    risk: Literal["low", "medium", "high"] = "low"
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    source_refs: list[str] = Field(min_length=1, max_length=32)
    customer_goal_ids: list[str] = Field(default_factory=list, max_length=32)
    customer_goal_bindings: list[CustomerGoalBinding] = Field(default_factory=list, max_length=32)
    hypothesis: BetHypothesis | None = None
    input_data: dict[str, Any] = Field(default_factory=dict, max_length=64)
    execution_binding: dict[str, str] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def bound_goals(self) -> Opportunity:
        ids = [row.customer_goal_id for row in self.customer_goal_bindings]
        if ids and (len(ids) != len(set(ids)) or set(ids) != set(self.customer_goal_ids)):
            raise ValueError("customer bindings must identify each approved goal exactly once")
        return self

    @field_validator("input_data")
    @classmethod
    def business_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        from modstore_server.strategic_execution_contract import validate_input

        return validate_input(value)


def _date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PortfolioError("invalid ISO timestamp") from None
    if parsed.tzinfo is None:
        raise PortfolioError("timestamp must include timezone")
    return parsed.astimezone(UTC)


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def optimize_portfolio(
    opportunities: list[dict[str, Any]],
    limits: dict[str, Any],
    *,
    max_selected: int | None = None,
    groups: list[tuple[list[str], dict[str, int]]] | None = None,
) -> dict[str, Any]:
    """Select a dependency-complete portfolio within all three resource caps."""
    from ortools.sat.python import cp_model

    cap = PortfolioLimits.model_validate(limits)
    maximum = COMPANY_MAX_CANDIDATES if groups is not None else 128
    if not 1 <= len(opportunities) <= maximum:
        raise PortfolioError(f"allocation requires 1..{maximum} opportunities")
    rows = [Opportunity.model_validate(row) for row in opportunities]
    by_id = {row.opportunity_id: row for row in rows}
    if len(by_id) != len(rows):
        raise PortfolioError("duplicate opportunity_id")
    graph = {row.opportunity_id: set(row.depends_on) for row in rows}
    if any(dep not in by_id for deps in graph.values() for dep in deps):
        raise PortfolioError("unknown opportunity dependency")
    order = list(TopologicalSorter(graph).static_order())
    model = cp_model.CpModel()
    variables = {key: model.new_bool_var(f"opportunity_{index}") for index, key in enumerate(order)}
    if max_selected is not None:
        model.add(sum(variables.values()) <= max_selected)
    for key in RESOURCES:
        model.add(
            sum(getattr(row, key) * variables[row.opportunity_id] for row in rows)
            <= getattr(cap, key)
        )
    grouped: set[str] = set()
    for identifiers, budget in groups or []:
        if (
            not identifiers
            or len(set(identifiers)) != len(identifiers)
            or not set(identifiers).issubset(by_id)
            or grouped.intersection(identifiers)
            or any(
                type(budget.get(key)) is not int or budget[key] < 0 for key in (*RESOURCES, "slots")
            )
        ):
            raise PortfolioError("invalid disjoint approved allocation groups")
        grouped.update(identifiers)
        model.add(sum(variables[key] for key in identifiers) <= budget["slots"])
        for resource in RESOURCES:
            model.add(
                sum(getattr(by_id[key], resource) * variables[key] for key in identifiers)
                <= budget[resource]
            )
    if groups is not None and grouped != set(by_id):
        raise PortfolioError("every company candidate requires its own portfolio limits")
    for row in rows:
        if row.risk == "high":
            model.add(variables[row.opportunity_id] == 0)
        for dep in row.depends_on:
            model.add(variables[row.opportunity_id] <= variables[dep])
    # Each boolean coefficient is below 2**31 (upstream OR-Tools issue #5293).
    utility = sum(
        row.value_score * row.confidence_bps * variables[row.opportunity_id] for row in rows
    )
    model.maximize(utility)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise PortfolioError("portfolio solver could not prove a feasible allocation")
    selected = [key for key in order if solver.value(variables[key])]
    optimal = status == cp_model.OPTIMAL
    if groups is not None and optimal and (remaining := 2.0 - solver.wall_time) > 0.005:
        # Stable FIFO only breaks equal utility. It cannot outweigh a more
        # valuable approved choice or introduce large mixed-radix coefficients.
        optimum = sum(by_id[key].value_score * by_id[key].confidence_bps for key in selected)
        model.add(utility == optimum)
        model.maximize(
            sum((len(order) - index) * variables[key] for index, key in enumerate(order))
        )
        solver.parameters.max_time_in_seconds = remaining
        tied = solver.solve(model)
        if tied in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            selected = [key for key in order if solver.value(variables[key])]
    allocation = {key: sum(getattr(by_id[item], key) for item in selected) for key in RESOURCES}
    if any(allocation[key] > getattr(cap, key) for key in RESOURCES) or any(
        by_id[key].risk == "high" or not set(by_id[key].depends_on).issubset(selected)
        for key in selected
    ):
        raise PortfolioError("optimizer returned an invalid allocation")
    for identifiers, budget in groups or []:
        chosen = set(identifiers).intersection(selected)
        if len(chosen) > budget["slots"] or any(
            sum(getattr(by_id[key], resource) for key in chosen) > budget[resource]
            for resource in RESOURCES
        ):
            raise PortfolioError("optimizer exceeded an approved portfolio group")
    return {
        "solver": "google/or-tools@9.15.6755/CP-SAT",
        "optimal": optimal,
        "selected": selected,
        "deferred": [key for key in order if key not in selected],
        "allocation": allocation,
    }


def create_portfolio_proposal(
    *,
    owner_user_id: int,
    goal: str,
    period: str,
    limits: dict[str, Any],
    opportunities: list[dict[str, Any]],
    idempotency_key: str,
) -> dict[str, Any]:
    """Create a reviewable financial proposal; never approve or spend its budget."""
    if (
        type(owner_user_id) is not int
        or owner_user_id <= 0
        or not goal.strip()
        or not idempotency_key.strip()
    ):
        raise PortfolioError("owner, goal and idempotency key are required")
    from modstore_server.strategic_company_resources import bind_limits

    cap = PortfolioLimits.model_validate(
        bind_limits(owner_user_id, PortfolioLimits.model_validate(limits).model_dump())
    )
    if _date(cap.expires_at) <= datetime.now(UTC):
        raise PortfolioError("budget authorization must have a future expiry")
    from modstore_server.strategic_execution_contract import freeze_execution

    rows = [
        freeze_execution(owner_user_id, Opportunity.model_validate(row).model_dump())
        for row in opportunities
    ]
    allocation = optimize_portfolio(rows, cap.model_dump())
    proposal = {
        "schema": SCHEMA,
        "owner_user_id": owner_user_id,
        "goal": goal[:4000],
        "period": period[:64],
        "limits": cap.model_dump(),
        "opportunities": rows,
    }
    proposal_hash = digest(proposal)
    record = StrategicDecisionLedger(evaluator=AutonomyEvaluator()).propose(
        title=f"战略资源组合：{goal[:180]}",
        action="financial allocate strategy portfolio",
        proposer=DecisionProposer(
            actor=f"user:{owner_user_id}",
            rationale="bounded strategy allocation",
            payload={**proposal, "proposal_sha256": proposal_hash},
        ),
        decision_type=DecisionType.STRATEGIC,
        scope="strategy_portfolio",
        scope_ref=f"user:{owner_user_id}:{period[:64]}",
        execution_plan=allocation,
        idempotency_key=f"portfolio:{owner_user_id}:{idempotency_key[:160]}",
    )
    if record.decision_payload.get("proposal_sha256") != proposal_hash:
        raise PortfolioError("idempotency key already belongs to a different proposal")
    return {"schema": SCHEMA, "decision": record.to_dict(), "plan": allocation}


def _row(
    session: Any, decision_id: str, owner_user_id: int | None = None
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    row = session.execute(
        select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
    ).scalar_one_or_none()
    if row is None:
        raise PortfolioError("portfolio not found")
    proposal = json.loads(row.decision_payload_json or "{}")
    if proposal.get("schema") != SCHEMA or (
        owner_user_id is not None and proposal.get("owner_user_id") != owner_user_id
    ):
        raise PortfolioError("portfolio not found for owner")
    return row, proposal, json.loads(row.execution_result_json or "{}")


def mutate_portfolio(
    decision_id: str, mutate: Callable[..., T], *, owner_user_id: int | None = None
) -> T:
    """Atomically change the existing ledger and action rows, including SQLite."""
    from modstore_server.strategic_company_accounting import synchronize_portfolio
    from modstore_server.strategic_company_resources import CompanyConflict

    for attempt in range(6):
        with get_session_factory()() as session:
            row, proposal, state = _row(session, decision_id, owner_user_id)
            previous = row.execution_result_json
            previous_updated_at = row.updated_at
            before = json.loads(previous or "{}")
            expected_status, expected_payload, expected_actor = (
                row.status,
                row.decision_payload_json,
                row.decided_by,
            )
            result = mutate(row, proposal, state, session)
            now = datetime.now(UTC)
            values = {
                "execution_result_json": _json(state),
                # Bounded consumers order by this stamp. A stopped/backward
                # wall clock must not move a checked portfolio to the front.
                "updated_at": (
                    max(now, previous_updated_at.replace(tzinfo=UTC) + timedelta(microseconds=1))
                    if previous_updated_at
                    else now
                ),
                "status": row.status,
                "decided_by": row.decided_by,
                "decided_at": row.decided_at,
                "review_notes": row.review_notes,
            }
            session.expunge(row)
            try:
                synchronize_portfolio(session, decision_id, proposal, before, state)
                changed = cast(
                    CursorResult[Any],
                    session.execute(
                        update(StrategicDecision)
                        .where(
                            StrategicDecision.decision_id == decision_id,
                            StrategicDecision.execution_result_json == previous,
                            StrategicDecision.updated_at == previous_updated_at,
                            StrategicDecision.status == expected_status,
                            StrategicDecision.decision_payload_json == expected_payload,
                            StrategicDecision.decided_by == expected_actor,
                        )
                        .values(**values)
                    ),
                ).rowcount
                if changed != 1:
                    session.rollback()
                    continue
                session.commit()
                return result
            except (CompanyConflict, IntegrityError, OperationalError) as exc:
                session.rollback()
                if attempt == 5:
                    if isinstance(exc, CompanyConflict):
                        raise PortfolioError(
                            "company resource capacity changed; retry when available"
                        ) from exc
                    raise
    raise PortfolioError("concurrent portfolio change; retry with the same identity")


def portfolio_principal_active(principal: Any) -> bool:
    """Shared revocation rule for scheduling and every new execution reservation."""
    return bool(
        principal is not None
        and principal.is_admin
        and getattr(principal, "is_active", True) is not False
        and principal.deleted_at is None
        and principal.account_state not in {"disabled", "suspended", "blocked", "deleted"}
    )


def require_active_portfolio_owner(owner_user_id: int, session: Any = None) -> None:
    from modstore_server.db.identity import User

    if session is None:
        with get_session_factory()() as owned_session:
            require_active_portfolio_owner(owner_user_id, owned_session)
        return
    if not portfolio_principal_active(session.get(User, owner_user_id)):
        raise PortfolioError("portfolio owner is no longer an active administrator")


def require_authorization(
    row: Any, proposal: dict[str, Any], state: dict[str, Any], *, session: Any = None
) -> None:
    from modstore_server.strategic_company_resources import require_company_authorization

    require_active_portfolio_owner(proposal["owner_user_id"], session)
    require_company_authorization(proposal, session)
    if row.status not in {"approved", "executing"} or row.decided_by not in {
        "user",
        "council-vote",
    }:
        raise PortfolioError("portfolio requires an existing human/council budget approval")
    if _date(proposal["limits"]["expires_at"]) <= datetime.now(UTC):
        raise PortfolioError("portfolio authorization expired")
    authorization = state.get("authorization", {})
    if not (
        authorization.get("actor")
        and authorization.get("user_id") == proposal["owner_user_id"]
        and authorization.get("proposal_sha256") == proposal["proposal_sha256"]
    ):
        raise PortfolioError("portfolio requires authenticated approval bound to this proposal")
    canonical = {
        key: proposal[key]
        for key in ("schema", "owner_user_id", "goal", "period", "limits", "opportunities")
    }
    if (
        digest(canonical) != proposal.get("proposal_sha256")
        or state.get("proposal_sha256", proposal["proposal_sha256"]) != proposal["proposal_sha256"]
    ):
        raise PortfolioError("approved portfolio content changed")
    if state.get("halted"):
        raise PortfolioError(f"portfolio stopped: {state.get('stop_reason', 'guardrail')}")
    from modstore_server.xiaoc_life_store import LifePolicyError, portfolio_life_guard

    try:
        portfolio_life_guard(row.decision_id, proposal, state)
    except LifePolicyError as exc:
        raise PortfolioError(str(exc)) from exc


def plan_portfolio(decision_id: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    """Freeze approved inputs and create durable dependency-linked action items."""

    def apply(
        row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any
    ) -> dict[str, Any]:
        require_authorization(row, proposal, state)
        if state.get("plan"):
            return dict(state["plan"])
        plan = optimize_portfolio(proposal["opportunities"], proposal["limits"])
        now = datetime.now(UTC)
        for opportunity in proposal["opportunities"]:
            if opportunity["opportunity_id"] in plan["selected"]:
                action_id = "portfolio-" + digest([decision_id, opportunity["opportunity_id"]])[:32]
                session.add(
                    StrategicActionItem(
                        action_id=action_id,
                        decision_id=decision_id,
                        description=opportunity["task"],
                        assigned_to=opportunity["employee_id"],
                        status="pending",
                        due_at=_date(proposal["limits"]["expires_at"]),
                        result_json=_json(
                            {"schema": SCHEMA, "opportunity_id": opportunity["opportunity_id"]}
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                )
        state.update(
            {
                "schema": SCHEMA,
                "proposal_sha256": proposal["proposal_sha256"],
                "plan": plan,
                "tasks": {},
                "reviews": [],
                "started_at": now.isoformat(),
                "halted": False,
            }
        )
        row.status = "executing"
        return plan

    return mutate_portfolio(decision_id, apply, owner_user_id=owner_user_id)


def portfolio_status(decision_id: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    with get_session_factory()() as session:
        row, proposal, state = _row(session, decision_id, owner_user_id)
        return {
            "schema": SCHEMA,
            "decision_id": decision_id,
            "status": row.status,
            "owner_user_id": proposal["owner_user_id"],
            "goal": proposal["goal"],
            "limits": proposal["limits"],
            "opportunities": proposal["opportunities"],
            "proposal_sha256": proposal["proposal_sha256"],
            **state,
        }


def authorize_portfolio(
    decision_id: str,
    *,
    owner_user_id: int,
    actor: str,
    expected_proposal_sha256: str,
    review_notes: str = "",
) -> dict[str, Any]:
    """Called only with the authenticated administrator identity from the API."""
    if not actor.strip():
        raise PortfolioError("authenticated approver is required")

    def apply(
        row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any
    ) -> dict[str, Any]:
        from modstore_server.strategic_company_resources import require_company_authorization

        require_active_portfolio_owner(owner_user_id, _session)
        require_company_authorization(proposal, _session)
        if row.status != "proposed" or proposal["proposal_sha256"] != expected_proposal_sha256:
            raise PortfolioError("portfolio approval state or proposal hash changed")
        if _date(proposal["limits"]["expires_at"]) <= datetime.now(UTC):
            raise PortfolioError("portfolio authorization expired")
        now = datetime.now(UTC)
        state["authorization"] = {
            "actor": actor,
            "user_id": owner_user_id,
            "proposal_sha256": expected_proposal_sha256,
            "approved_at": now.isoformat(),
        }
        row.status, row.decided_by, row.decided_at, row.review_notes = (
            "approved",
            "user",
            now,
            review_notes[:4000],
        )
        return {
            "decision_id": decision_id,
            "status": "approved",
            "authorization": state["authorization"],
        }

    return mutate_portfolio(decision_id, apply, owner_user_id=owner_user_id)


def stop_portfolio(
    decision_id: str, *, owner_user_id: int, actor: str, reason: str
) -> dict[str, Any]:
    if not actor.strip() or not reason.strip():
        raise PortfolioError("authenticated actor and stop reason are required")

    def apply(
        row: Any, _proposal: dict[str, Any], state: dict[str, Any], _session: Any
    ) -> dict[str, Any]:
        state.update(
            halted=True,
            stop_reason=reason[:500],
            stopped_by=actor,
            stopped_at=datetime.now(UTC).isoformat(),
        )
        row.status = "withdrawn"
        return {"decision_id": decision_id, "status": row.status, "halted": True}

    return mutate_portfolio(decision_id, apply, owner_user_id=owner_user_id)
