"""Independent decision-review regression tests; real solver in governance CI."""

from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import business_decision_review as review
from modstore_server import strategic_portfolio as portfolio
from modstore_server.strategic_portfolio import digest
from tests.test_strategic_portfolio import database, limits, opportunity, seed_owner


def test_unknown_and_nonoverlapping_temporal_evidence():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(40):
        left = start + timedelta(days=index * 2)
        rows.append({
            "decision_id": str(index),
            "snapshot_sha256": digest(["snapshot", index]),
            "evidence_sha256": digest(["source", index]),
            "window_start": left.isoformat(),
            "window_end": (left + timedelta(days=1)).isoformat(),
            "value": float(index % 2),
            "hit": index % 2,
            "accrued_cost_cents": 100,
        })
    assert review.forecast(rows[:39])["probability_of_target"] is None
    assert review.forecast(rows[:1] * 50)["sample_count"] == 1
    result = review.forecast(rows)
    assert result["sample_count"] == 40
    if result["status"] == "unknown_statistics_dependency_unavailable":
        assert result["probability_of_target"] is None
    else:
        assert result["status"] == "historical_constant_rate_temporally_checked"
        assert result["probability_of_target"] == 0.5
        assert result["holdout_brier"] == 0.25
        assert result["risk_of_target_miss"] == 0.5


def test_independent_measurement_checks_original_snapshot_and_settlement():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    target = {
        "hypothesis": "measure service",
        "metric_id": "slo_availability",
        "threshold": 0.9,
        "direction": "max",
        "window_days": 1,
        "kill_criteria": ["miss"],
        "kill_on_miss": True,
    }
    item = {"opportunity_id": "op-1", "hypothesis": target}
    snapshot = {
        "opportunity_id": "op-1",
        "hypothesis": target,
        "evidence": {"value": 0.8, "evidence_sha256": digest("source")},
        "verdict": "miss",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "reviewed_at": end.isoformat(),
    }
    snapshot["snapshot_sha256"] = digest(snapshot)
    task = {
        "status": "completed",
        "calls": {"a": {"status": "settled"}},
        "started_at": start.isoformat(),
        "accrued_cost_cents": 15,
    }
    state = {"tasks": {"op-1": task}, "hypothesis_outcomes": {"op-1": snapshot}}
    assert review.closed_sample(item, state, end)["hit"] == 0
    assert review.closed_sample(item, state, start) is None
    task["calls"]["a"]["status"] = "unknown"
    assert review.closed_sample(item, state, end) is None
    task["calls"]["a"]["status"] = "settled"
    snapshot["evidence"]["value"] = 0.99
    assert review.closed_sample(item, state, end) is None


def test_review_is_part_of_original_proposal_content():
    proposal = {
        "schema": "schema",
        "owner_user_id": 17,
        "goal": "goal",
        "period": "period",
        "limits": {},
        "opportunities": [],
        "decision_review": {"selected_for_approval": "no_action"},
    }
    original = digest(review.proposal_content(proposal))
    proposal["decision_review"]["selected_for_approval"] = "changed"
    assert digest(review.proposal_content(proposal)) != original
    proposal.pop("decision_review")
    assert "decision_review" not in review.proposal_content(proposal)


def test_original_sql_approval_freezes_options_and_never_executes_alternative(database, monkeypatch):
    seed_owner(database)
    monkeypatch.setattr(review, "get_session_factory", lambda: database)
    options = {
        "alternatives": [
            {
                "title": "alternative",
                "task": "other measurable task",
                "tradeoff": "unverified",
                "evidence_refs": ["incident:1"],
            }
        ],
        "context_sha256": digest("observed world"),
        "evidence_refs": ["incident:1"],
    }
    kwargs = dict(
        owner_user_id=7, goal="Improve delivery", period="decision-review",
        limits=limits(), opportunities=[opportunity()], idempotency_key="same-review",
        decision_options=options,
    )
    first = portfolio.create_portfolio_proposal(**kwargs)
    again = portfolio.create_portfolio_proposal(**kwargs)
    assert first["decision"]["decision_id"] == again["decision"]["decision_id"]
    assert first["decision_review"] == again["decision_review"]
    comparison = first["decision_review"]
    assert comparison["options"][0]["option_id"] == "no_action"
    assert sum(row["feasible"] for row in comparison["options"]) == 3
    assert comparison["selection_basis"] == "unranked_experiment_for_human_review"
    decision_id = first["decision"]["decision_id"]
    status = portfolio.portfolio_status(decision_id, owner_user_id=7)
    assert status["decision_review"] == comparison
    assert len(status["opportunities"]) == 1
    assert status["status"] == "proposed"
    with pytest.raises(portfolio.PortfolioError):
        portfolio.plan_portfolio(decision_id, owner_user_id=7)
    portfolio.authorize_portfolio(
        decision_id, owner_user_id=7, actor="admin",
        expected_proposal_sha256=status["proposal_sha256"],
    )
    plan = portfolio.plan_portfolio(decision_id, owner_user_id=7)
    assert plan["selected"] == [comparison["selected_for_approval"]]


def test_high_risk_cannot_become_executable_and_no_action_remains(database, monkeypatch):
    seed_owner(database)
    monkeypatch.setattr(review, "get_session_factory", lambda: database)
    response = portfolio.create_portfolio_proposal(
        owner_user_id=7, goal="Improve delivery", period="blocked-review", limits=limits(),
        opportunities=[opportunity(risk="high")], idempotency_key="blocked-review",
        decision_options={
            "alternatives": [], "context_sha256": digest("observed world"),
            "evidence_refs": ["incident:1"],
        },
    )
    assert response["decision"] is None
    assert response["decision_review"]["selected_for_approval"] == "no_action"
    assert not response["decision_review"]["options"][1]["feasible"]
