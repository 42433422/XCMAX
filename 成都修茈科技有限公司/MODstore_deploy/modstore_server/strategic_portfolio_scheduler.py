"""Advance only authenticated, unexpired portfolio mandates on the existing scheduler."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from modstore_server.db.db_base import get_session_factory
from modstore_server.db.identity import User
from modstore_server.db.strategic import StrategicDecision
from modstore_server.strategic_portfolio import (
    PortfolioError,
    _date,
    portfolio_principal_active,
    portfolio_status,
    stop_portfolio,
)
from modstore_server.strategic_portfolio_runtime import review_portfolio, run_portfolio_cycle


def tick(*, limit: int = 10) -> dict[str, Any]:
    """Recheck the principal and guardrails before every bounded execution cycle."""
    with get_session_factory()() as session:
        ids = session.scalars(
            select(StrategicDecision.decision_id)
            .where(
                StrategicDecision.scope == "strategy_portfolio",
                StrategicDecision.status.in_(("approved", "executing")),
            )
            .order_by(StrategicDecision.updated_at)
            .limit(max(1, min(limit, 100)))
        ).all()
    results: list[dict[str, Any]] = []
    for decision_id in ids:
        try:
            status = portfolio_status(decision_id)
            owner = status["owner_user_id"]
            with get_session_factory()() as session:
                principal = session.get(User, owner)
                authorized = portfolio_principal_active(principal)
            reason = ""
            if not authorized:
                reason = "approving_principal_no_longer_authorized"
            elif _date(status["limits"]["expires_at"]) <= datetime.now(UTC):
                reason = "authorization_expired"
            elif status.get("halted"):
                reason = str(status.get("stop_reason") or "portfolio_guardrail")
            if reason:
                stopped = stop_portfolio(
                    decision_id,
                    owner_user_id=owner,
                    actor="scheduler:strategic-portfolio",
                    reason=reason,
                )
                results.append({**stopped, "reason": reason})
                continue
            if status.get("started_at"):
                review_portfolio(decision_id, owner_user_id=owner)
                if portfolio_status(decision_id, owner_user_id=owner).get("halted"):
                    results.append({"decision_id": decision_id, "status": "halted"})
                    continue
            execution = run_portfolio_cycle(decision_id, owner_user_id=owner, max_tasks=1)
            review = review_portfolio(decision_id, owner_user_id=owner)
            results.append({"decision_id": decision_id, "execution": execution, "review": review})
        except PortfolioError as exc:
            # A revoked/changed mandate never becomes a blanket retry permission.
            results.append({"decision_id": decision_id, "status": "blocked", "reason": str(exc)})
    return {"selected": len(ids), "results": results}
