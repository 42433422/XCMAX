"""Discovery persists approval proposals without dispatching unapproved work."""

import asyncio
import json

import pytest
from sqlalchemy import select

from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import limits, opportunity, seed_owner


def test_legacy_bets_cannot_self_authorize_or_dispatch():
    from modstore_server import strategy_bets, strategy_planner

    with pytest.raises(ValueError, match="authenticated"):
        strategy_bets.register_bet(bet_id="legacy", budget={"tokens": 1_000_000})
    with pytest.raises(strategy_bets.BudgetExceeded):
        strategy_bets.record_spend("legacy", tokens=1)
    assert strategy_planner.dispatch_bet({})["status"] == "blocked"


def test_scheduled_discovery_persists_once_and_never_approves(database, monkeypatch):
    from modstore_server import strategy_planner

    seed_owner(database)
    calls = []

    async def discover(**_kwargs):
        calls.append(True)
        return {"source": "live_metric", "opportunities": [opportunity()]}

    monkeypatch.setattr(runtime, "discover_portfolio_opportunities", discover)
    template = {
        "owner_user_id": 7,
        "goal": "Improve delivery",
        "limits": limits(),
        "period_days": 7,
        "use_llm": False,
    }
    first = asyncio.run(strategy_planner.run_scheduled_discovery(template=template))
    second = asyncio.run(strategy_planner.run_scheduled_discovery(template=template))
    assert first["status"] == "awaiting_approval" and second["idempotent"]
    assert len(calls) == 1
    state = p.portfolio_status(first["registered"][0], owner_user_id=7)
    assert state["status"] == "proposed" and not state.get("authorization")
    with pytest.raises(p.PortfolioError):
        runtime.run_portfolio_cycle(state["decision_id"])
    from modstore_server.db.llm_chat import LlmClientRequest

    with database() as session:
        receipt = session.execute(select(LlmClientRequest)).scalar_one()
        receipt.state, receipt.done_json = "processing", '{"status":"running"}'
        session.commit()
    recovered = asyncio.run(strategy_planner.run_scheduled_discovery(template=template))
    assert recovered["recovered"] and recovered["registered"] == first["registered"]
    assert len(calls) == 1


def test_historical_domain_aliases_retain_unrated_status_without_stale_gaps(tmp_path, monkeypatch):
    from modstore_server import strategy_planner

    report = tmp_path / "domain.json"
    report.write_text(
        json.dumps(
            {
                "audited_at": "2026-11-15T00:00:00+00:00",
                "source": "historical-3396",
                "domains": [
                    {
                        "domain_id": "di-layering",
                        "status": "UNRATED",
                        "score": 9,
                        "blocking_gap": "outdated gap must not become current evidence",
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("MODSTORE_DOMAIN_AUDIT_PATH", str(report))
    context = strategy_planner._domain_status()
    assert context["domains"][0]["domain_id"] == "architecture"
    assert context["domains"][0]["score"] is None
    assert context["audited_at"].startswith("2026-11-15")
    assert "blocking_gap" not in json.dumps(context)
