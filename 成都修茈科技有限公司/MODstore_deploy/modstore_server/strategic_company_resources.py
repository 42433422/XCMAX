"""Deployment-scoped company mandate over the existing strategic SQL ledger.

SQLAlchemy conditional UPDATE and PostgreSQL row conflict semantics provide the
transaction boundary. Unknown external work is an encumbrance, not a TTL lease
that can safely decay (compare Prefect's global concurrency acquisition model).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Callable, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError

from modstore_server.db.strategic import StrategicDecision
from modstore_server.strategic_portfolio import (
    RESOURCES,
    ModelTariff,
    PortfolioError,
    _date,
    _json,
    digest,
    require_active_portfolio_owner,
)

SCHEMA = "xcagi.strategy_company_budget/v1"
POLICY_SCHEMA = "xcagi.strategy_company_policy/v1"
POLICY_ID = "strategy-company-active-policy"
CONTROL_ENV = "MODSTORE_STRATEGY_COMPANY_CONTROL"
T = TypeVar("T")


class CompanyConflict(RuntimeError):
    """Retry the complete transaction; no resource/action row may commit alone."""


class CompanyControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scope: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,96}$")
    authorizer_user_ids: list[int] = Field(min_length=1, max_length=128)
    eligible_owner_user_ids: list[int] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def principals(self) -> CompanyControl:
        if any(item <= 0 for item in self.authorizer_user_ids + self.eligible_owner_user_ids):
            raise ValueError("company principals must be positive existing user IDs")
        return self


class CompanyLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cost_cents: int = Field(ge=0, le=100_000_000)
    tokens: int = Field(ge=0, le=1_000_000_000)
    compute_seconds: int = Field(ge=1, le=7_776_000)
    max_parallel: int = Field(ge=1, le=128)
    expires_at: str = Field(min_length=20, max_length=40)
    tariffs: list[ModelTariff] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def valid(self) -> CompanyLimits:
        _date(self.expires_at)
        if len({(row.provider, row.model) for row in self.tariffs}) != len(self.tariffs):
            raise ValueError("duplicate company model tariffs")
        return self


def control() -> CompanyControl | None:
    raw = os.getenv(CONTROL_ENV, "").strip()
    return CompanyControl.model_validate_json(raw) if raw else None


def transaction(operation: Callable[[Any], T]) -> T:
    from modstore_server.db.db_base import get_session_factory

    for attempt in range(8):
        with get_session_factory()() as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except (CompanyConflict, IntegrityError, OperationalError):
                session.rollback()
                if attempt == 7:
                    raise PortfolioError("concurrent company resource change; retry") from None
    raise AssertionError("unreachable company transaction")


def load_row(session: Any, decision_id: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    row = session.execute(
        select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
    ).scalar_one_or_none()
    if row is None:
        raise PortfolioError("company budget not found")
    proposal = json.loads(row.decision_payload_json or "{}")
    if proposal.get("schema") != SCHEMA:
        raise PortfolioError("company budget not found")
    canonical = {
        key: proposal[key]
        for key in (
            "schema",
            "company_scope",
            "owner_user_id",
            "period",
            "limits",
            "member_owner_ids",
            "replaces_budget_id",
            "previous_resource_totals",
        )
    }
    if digest(canonical) != proposal.get("proposal_sha256"):
        raise PortfolioError("company budget approved content changed")
    return row, proposal, json.loads(row.execution_result_json or "{}")


def write_row(session: Any, row: Any, state: dict[str, Any], **values: Any) -> None:
    expected = (
        row.decision_id,
        row.execution_result_json,
        row.status,
        row.decision_payload_json,
        row.decided_by,
    )
    state["revision"] = int(state.get("revision", 0)) + 1
    session.expunge(row)
    changed = cast(
        CursorResult[Any],
        session.execute(
            update(StrategicDecision)
            .where(
                StrategicDecision.decision_id == expected[0],
                StrategicDecision.execution_result_json == expected[1],
                StrategicDecision.status == expected[2],
                StrategicDecision.decision_payload_json == expected[3],
                StrategicDecision.decided_by == expected[4],
            )
            .values(execution_result_json=_json(state), updated_at=datetime.now(UTC), **values)
        ),
    ).rowcount
    if changed != 1:
        raise CompanyConflict("company resource compare-and-swap lost")


def _policy(session: Any) -> Any:
    return session.execute(
        select(StrategicDecision).where(StrategicDecision.decision_id == POLICY_ID)
    ).scalar_one_or_none()


def _authorizer(session: Any, user_id: int) -> CompanyControl:
    configured = control()
    if configured is None or user_id not in configured.authorizer_user_ids:
        raise PortfolioError("company budget authorizer is not configured by the operator")
    require_active_portfolio_owner(user_id, session)
    return configured


def active_budget(
    session: Any, owner_user_id: int, expected_id: str = "", *, touch_policy: bool = False
) -> tuple[Any, dict[str, Any], dict[str, Any]] | None:
    configured, policy = control(), _policy(session)
    if configured is None and policy is None and not expected_id:
        return None
    if configured is None or policy is None:
        raise PortfolioError("company control requires its configured and approved budget")
    link = json.loads(policy.execution_result_json or "{}")
    if link.get("company_scope") != configured.scope:
        raise PortfolioError("company deployment scope changed; operator review required")
    budget_id = str(link.get("budget_id") or "")
    if expected_id and budget_id != expected_id:
        raise PortfolioError("portfolio company mandate changed; a new approval is required")
    row, proposal, state = load_row(session, budget_id)
    authorization = state.get("authorization", {})
    if (
        row.status != "approved"
        or row.decided_by != "user"
        or state.get("halted")
        or authorization.get("proposal_sha256") != proposal["proposal_sha256"]
        or not authorization.get("actor")
    ):
        raise PortfolioError("company budget is not approved or has been revoked/stopped")
    _authorizer(session, int(authorization.get("user_id") or 0))
    if (
        proposal["company_scope"] != configured.scope
        or owner_user_id not in proposal["member_owner_ids"]
        or owner_user_id not in configured.eligible_owner_user_ids
    ):
        raise PortfolioError("portfolio owner is not a member of the approved company budget")
    require_active_portfolio_owner(owner_user_id, session)
    if _date(proposal["limits"]["expires_at"]) <= datetime.now(UTC):
        raise PortfolioError("company budget authorization expired")
    if touch_policy:
        write_row(session, policy, link)
    return row, proposal, state


def bind_limits(owner_user_id: int, limits: dict[str, Any], session: Any = None) -> dict[str, Any]:
    if session is None:
        from modstore_server.db.db_base import get_session_factory

        with get_session_factory()() as owned:
            return bind_limits(owner_user_id, limits, owned)
    budget = active_budget(session, owner_user_id, str(limits.get("company_budget_id") or ""))
    if budget is None:
        return dict(limits)
    row, proposal, _state = budget
    approved = proposal["limits"]
    if any(limits[key] > approved[key] for key in (*RESOURCES, "max_parallel")):
        raise PortfolioError("portfolio limits exceed the company mandate")
    if _date(limits["expires_at"]) > _date(approved["expires_at"]):
        raise PortfolioError("portfolio expiry exceeds the company mandate")
    tariffs = {(item["provider"], item["model"]): item for item in approved["tariffs"]}
    for item in limits["tariffs"]:
        tariff = tariffs.get((item["provider"], item["model"]))
        if tariff is None or any(
            item[key] != tariff[key]
            for key in ("input_cents_per_million", "output_cents_per_million")
        ):
            raise PortfolioError("portfolio tariff is outside the approved company mandate")
    return {**limits, "company_budget_id": row.decision_id}


def require_company_authorization(proposal: dict[str, Any], session: Any = None) -> None:
    limits = bind_limits(proposal["owner_user_id"], proposal["limits"], session)
    if limits.get("company_budget_id") != proposal["limits"].get("company_budget_id"):
        raise PortfolioError("existing portfolio requires approval under the company mandate")


def totals(state: dict[str, Any]) -> dict[str, Any]:
    allocations = state.get("allocations", {}).values()
    return {
        kind: {key: sum(int(item[kind][key]) for item in allocations) for key in RESOURCES}
        for kind in ("spent", "held")
    } | {"slots": sum(int(item["slots"]) for item in allocations)}


def remaining(session: Any, proposal: dict[str, Any]) -> dict[str, int] | None:
    budget = active_budget(
        session, proposal["owner_user_id"], str(proposal["limits"].get("company_budget_id") or "")
    )
    if budget is None:
        return None
    _row, company, state = budget
    used = totals(state)
    return {
        key: max(0, company["limits"][key] - used["spent"][key] - used["held"][key])
        for key in RESOURCES
    } | {"slots": max(0, company["limits"]["max_parallel"] - used["slots"])}


def create_company_proposal(
    *,
    authorizer_user_id: int,
    period: str,
    limits: dict[str, Any],
    member_owner_ids: list[int],
    idempotency_key: str,
) -> dict[str, Any]:
    from modstore_server.db.db_base import get_session_factory
    from modstore_server.strategic_layer import (
        AutonomyEvaluator,
        DecisionProposer,
        DecisionType,
        StrategicDecisionLedger,
    )

    cap = CompanyLimits.model_validate(limits)
    if (
        _date(cap.expires_at) <= datetime.now(UTC)
        or not period.strip()
        or not idempotency_key.strip()
    ):
        raise PortfolioError("company budget requires a period, stable identity and future expiry")
    with get_session_factory()() as session:
        configured = _authorizer(session, authorizer_user_id)
        if (
            not member_owner_ids
            or len(set(member_owner_ids)) != len(member_owner_ids)
            or not set(member_owner_ids).issubset(configured.eligible_owner_user_ids)
        ):
            raise PortfolioError("company members must be explicitly eligible operator principals")
        for owner in member_owner_ids:
            require_active_portfolio_owner(owner, session)
        policy = _policy(session)
        previous_id = (
            json.loads(policy.execution_result_json).get("budget_id", "") if policy else ""
        )
        previous_totals = totals(load_row(session, previous_id)[2]) if previous_id else totals({})
    proposal = {
        "schema": SCHEMA,
        "company_scope": configured.scope,
        "owner_user_id": authorizer_user_id,
        "period": period[:64],
        "limits": cap.model_dump(),
        "member_owner_ids": sorted(member_owner_ids),
        "replaces_budget_id": previous_id,
        "previous_resource_totals": previous_totals,
    }
    sha = digest(proposal)
    record = StrategicDecisionLedger(evaluator=AutonomyEvaluator()).propose(
        title=f"公司共享预算：{configured.scope} / {period[:64]}",
        action="financial allocate company resource budget",
        proposer=DecisionProposer(
            actor=f"user:{authorizer_user_id}",
            rationale="operator-scoped company budget mandate",
            payload={**proposal, "proposal_sha256": sha},
        ),
        decision_type=DecisionType.STRATEGIC,
        scope="strategy_company_budget",
        scope_ref=configured.scope,
        idempotency_key=f"company:{configured.scope}:{idempotency_key[:100]}",
    )
    if record.decision_payload.get("proposal_sha256") != sha:
        raise PortfolioError("company idempotency key belongs to a different proposal")
    return {"schema": SCHEMA, "decision": record.to_dict()}


def authorize_company(
    decision_id: str,
    *,
    authorizer_user_id: int,
    actor: str,
    expected_proposal_sha256: str,
    review_notes: str = "",
) -> dict[str, Any]:
    def apply(session: Any) -> dict[str, Any]:
        configured = _authorizer(session, authorizer_user_id)
        row, proposal, state = load_row(session, decision_id)
        if (
            not actor.strip()
            or row.status != "proposed"
            or proposal["proposal_sha256"] != expected_proposal_sha256
            or proposal["company_scope"] != configured.scope
            or not set(proposal["member_owner_ids"]).issubset(configured.eligible_owner_user_ids)
            or _date(proposal["limits"]["expires_at"]) <= datetime.now(UTC)
        ):
            raise PortfolioError("company approval state, content, membership or expiry changed")
        for owner in proposal["member_owner_ids"]:
            require_active_portfolio_owner(owner, session)
        policy = _policy(session)
        link = {"company_scope": configured.scope, "budget_id": decision_id}
        current_id = json.loads(policy.execution_result_json).get("budget_id", "") if policy else ""
        if proposal["replaces_budget_id"] != current_id:
            raise PortfolioError("company predecessor mandate changed; re-propose the budget")
        if policy is not None:
            previous = json.loads(policy.execution_result_json or "{}")
            if previous.get("company_scope") != configured.scope:
                raise PortfolioError("company deployment scope cannot be replaced by a member")
            link["revision"] = previous.get("revision", 0)
            write_row(session, policy, link)
            old_row, _old_proposal, old_state = load_row(session, previous["budget_id"])
            used = totals(old_state)
            if used["slots"] or any(used["held"].values()):
                raise PortfolioError("previous company budget retains unresolved resource holds")
            write_row(session, old_row, old_state, status="withdrawn")
        else:
            from modstore_server.strategic_company_accounting import require_no_unmanaged_work

            require_no_unmanaged_work(session)
            session.add(
                StrategicDecision(
                    decision_id=POLICY_ID,
                    title="Deployment company budget policy",
                    proposed_by="operator-config",
                    scope="strategy_company_policy",
                    scope_ref=configured.scope,
                    status="approved",
                    decided_by="user",
                    decision_payload_json=_json({"schema": POLICY_SCHEMA}),
                    execution_result_json=_json({**link, "revision": 1}),
                )
            )
        state.update(
            authorization={
                "actor": actor,
                "user_id": authorizer_user_id,
                "proposal_sha256": expected_proposal_sha256,
                "approved_at": datetime.now(UTC).isoformat(),
            },
            allocations={},
        )
        write_row(
            session,
            row,
            state,
            status="approved",
            decided_by="user",
            decided_at=datetime.now(UTC),
            review_notes=review_notes[:4000],
        )
        return {
            "decision_id": decision_id,
            "status": "approved",
            "authorization": state["authorization"],
        }

    return transaction(apply)


def revoke_company(
    decision_id: str, *, authorizer_user_id: int, actor: str, reason: str
) -> dict[str, Any]:
    def apply(session: Any) -> dict[str, Any]:
        configured = _authorizer(session, authorizer_user_id)
        row, proposal, state = load_row(session, decision_id)
        if proposal["company_scope"] != configured.scope or not actor.strip() or not reason.strip():
            raise PortfolioError("configured company authorizer and stop reason are required")
        state.update(
            halted=True,
            stop_reason=reason[:500],
            stopped_by=actor,
            stopped_at=datetime.now(UTC).isoformat(),
        )
        write_row(session, row, state, status="withdrawn")
        return {"decision_id": decision_id, "status": "withdrawn", **totals(state)}

    return transaction(apply)


def company_status(decision_id: str, *, owner_user_id: int) -> dict[str, Any]:
    from modstore_server.db.db_base import get_session_factory

    with get_session_factory()() as session:
        row, proposal, state = load_row(session, decision_id)
        configured = control()
        allowed = configured and (
            owner_user_id in configured.authorizer_user_ids
            or owner_user_id in proposal["member_owner_ids"]
        )
        if not allowed:
            raise PortfolioError("company budget not found for principal")
        require_active_portfolio_owner(owner_user_id, session)
        return {
            "schema": SCHEMA,
            "decision_id": decision_id,
            "status": row.status,
            "company_scope": proposal["company_scope"],
            "limits": proposal["limits"],
            "proposal_sha256": proposal["proposal_sha256"],
            "halted": state.get("halted", False),
            "stop_reason": state.get("stop_reason"),
            "totals": totals(state),
            "own_allocations": {
                key: value
                for key, value in state.get("allocations", {}).items()
                if value["owner_user_id"] == owner_user_id
            },
        }
