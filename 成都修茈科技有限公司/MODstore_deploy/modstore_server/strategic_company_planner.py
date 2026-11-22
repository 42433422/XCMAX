"""One CP-SAT choice across executable work inside the approved company pool.

This ranks original approved candidates. The existing portfolio transaction and
company CAS still acquire every real task, model reservation, and execution slot.
No other owner's authority or business input is returned to a caller.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, cast, func, select

from modstore_server.db.strategic import StrategicDecision
from modstore_server.strategic_company_resources import (
    _policy,
    active_budget,
    control,
    load_row,
    totals,
)
from modstore_server.strategic_portfolio import (
    COMPANY_MAX_CANDIDATES,
    RESOURCES,
    SCHEMA,
    PortfolioError,
    _date,
    digest,
    optimize_portfolio,
    require_authorization,
)


def _company_rows(session: Any, budget_id: str) -> Any:
    """Filter the company binding in SQL before loading private proposal bodies."""
    column = StrategicDecision.decision_payload_json
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        company_id = cast(column, JSON)["limits"]["company_budget_id"].as_string()
    elif dialect == "sqlite":
        company_id = func.json_extract(column, "$.limits.company_budget_id")
    else:
        raise PortfolioError("company planning requires the configured SQLite/PostgreSQL ledger")
    return session.scalars(
        select(StrategicDecision)
        .where(
            StrategicDecision.scope == "strategy_portfolio",
            StrategicDecision.status.in_(("approved", "executing")),
            company_id == budget_id,
        )
        .order_by(StrategicDecision.proposed_at, StrategicDecision.id)
        .execution_options(yield_per=32)
    )


def _confidence(item: dict[str, Any], proposal: dict[str, Any], state: dict[str, Any]) -> int:
    """Use the same bounded execution prior as the existing outcome reallocator."""
    approved = int(item["confidence_bps"])
    review = (state.get("reviews") or [{}])[-1]
    if not (
        review.get("decision") == "reallocate_within_approval"
        and review.get("usage_complete") is True
        and review.get("observation_complete") is True
    ):
        return approved
    by_id = {row["opportunity_id"]: row for row in proposal["opportunities"]}
    history = [
        task
        for key, task in state.get("tasks", {}).items()
        if by_id[key]["employee_id"] == item["employee_id"]
    ]
    succeeded = sum(1 for task in history if task["status"] == "completed")
    return approved * (succeeded + 1) // (len(history) + 1)


def _ready(
    row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any, current_id: str | None
) -> tuple[list[dict[str, Any]], dict[str, int]] | None:
    from modstore_server.strategic_portfolio_runtime import _consumed
    from modstore_server.xiaoc_life_store import LifePolicyError, require_life_task_capacity

    if proposal.get("schema") != SCHEMA:
        return None
    # The ordinary scheduler cannot restore another controller's life claim.
    if str(proposal.get("period", "")).startswith("xiaoc-life:") and row.decision_id != current_id:
        return None
    try:
        require_authorization(row, proposal, state, session=session)
    except PortfolioError:
        return None
    tasks, limits = state.get("tasks", {}), proposal["limits"]
    running = [task for task in tasks.values() if task["status"] in {"running", "waiting"}]
    if any(_date(task["deadline"]) <= datetime.now(UTC) for task in running):
        return None
    caps = {
        key: max(0, limits[key] - sum(_consumed(task, key) for task in tasks.values()))
        for key in RESOURCES
    }
    caps["slots"] = max(0, limits["max_parallel"] - len(running))
    if caps["slots"] <= 0 or caps["compute_seconds"] <= 0:
        return None
    by_id = {item["opportunity_id"]: item for item in proposal["opportunities"]}
    candidates = []
    for key, item in by_id.items():
        if (
            key in tasks
            or item["risk"] == "high"
            or any(tasks.get(dep, {}).get("status") != "completed" for dep in item["depends_on"])
        ):
            continue
        try:
            require_life_task_capacity(proposal, item["tokens"])
        except LifePolicyError:
            continue
        candidates.append(
            {**item, "depends_on": [], "confidence_bps": _confidence(item, proposal, state)}
        )
    return candidates, caps


def _select(
    session: Any,
    budget: tuple[Any, dict[str, Any], dict[str, Any]],
    *,
    current_id: str | None = None,
) -> dict[str, Any]:
    row, company, state = budget
    used = totals(state)
    remaining = {
        key: max(0, company["limits"][key] - used["spent"][key] - used["held"][key])
        for key in RESOURCES
    }
    slots = max(0, company["limits"]["max_parallel"] - used["slots"])
    result: dict[str, Any] = {
        "company_budget_id": row.decision_id,
        "company_revision": state.get("revision", 0),
        "selected": [],
        "candidate_count": 0,
    }
    if slots <= 0 or remaining["compute_seconds"] <= 0:
        return result
    candidates: list[dict[str, Any]] = []
    groups: list[tuple[list[str], dict[str, int]]] = []
    identities: dict[str, tuple[str, str]] = {}
    snapshots = []
    rows = _company_rows(session, row.decision_id)
    try:
        for portfolio in rows:
            proposal = json.loads(portfolio.decision_payload_json or "{}")
            snapshot = json.loads(portfolio.execution_result_json or "{}")
            prepared = _ready(portfolio, proposal, snapshot, session, current_id)
            if prepared is None or not prepared[0]:
                continue
            ready, caps = prepared
            keys = []
            for item in ready:
                identity = (str(portfolio.decision_id), item["opportunity_id"])
                key = "company-" + digest(identity)
                identities[key] = identity
                candidates.append({**item, "opportunity_id": key})
                keys.append(key)
            if len(candidates) > COMPANY_MAX_CANDIDATES:
                raise PortfolioError(
                    "company candidate snapshot exceeds the bounded solver capacity"
                )
            groups.append((keys, caps))
            snapshots.append(
                [portfolio.decision_id, proposal["proposal_sha256"], digest(snapshot), keys, caps]
            )
    finally:
        rows.close()
    if not candidates:
        return result
    allocation = optimize_portfolio(
        candidates,
        {
            **company["limits"],
            **remaining,
            "max_parallel": min(16, slots),
            "stop_loss_cents": remaining["cost_cents"],
        },
        max_selected=slots,
        groups=groups,
    )
    scores = {
        item["opportunity_id"]: item["value_score"] * item["confidence_bps"] for item in candidates
    }
    selected = sorted(allocation["selected"], key=lambda key: -scores[key])
    result.update(
        selected=[identities[key] for key in selected],
        candidate_count=len(candidates),
        snapshot_sha256=digest(snapshots),
        selection_sha256=digest({"snapshot": snapshots, "allocation": allocation}),
        solver=allocation["solver"],
        optimal=allocation["optimal"],
    )
    return result


def claim_candidates(
    session: Any, decision_id: str, proposal: dict[str, Any], state: dict[str, Any]
) -> list[str] | None:
    budget = active_budget(
        session, proposal["owner_user_id"], proposal["limits"].get("company_budget_id", "")
    )
    if budget is None:
        return None
    choice = _select(session, budget, current_id=decision_id)
    own = [key for portfolio_id, key in choice["selected"] if portfolio_id == decision_id]
    state["company_selection"] = {
        key: value for key, value in choice.items() if key != "selected"
    } | {"selected_opportunity_ids": own, "at": datetime.now(UTC).isoformat()}
    return own


def prioritized_portfolios(session: Any) -> list[str]:
    """Read-only scheduler hint; the actual claim recomputes it inside its CAS."""
    configured = control()
    if configured is None or (policy := _policy(session)) is None:
        return []
    link = json.loads(policy.execution_result_json or "{}")
    try:
        _row, proposal, _state = load_row(session, str(link.get("budget_id") or ""))
        for owner in proposal["member_owner_ids"]:
            try:
                budget = active_budget(session, owner, str(link["budget_id"]))
            except PortfolioError:
                continue
            if budget is not None:
                selection = _select(session, budget)
                return list(dict.fromkeys(identity[0] for identity in selection["selected"]))
    except PortfolioError:
        # Original per-portfolio authorization still reports the precise block.
        return []
    return []
