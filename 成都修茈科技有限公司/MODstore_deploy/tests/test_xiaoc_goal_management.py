"""Operating candidate invariants; no model, employee or approval mocks required."""

from datetime import UTC, datetime, timedelta

import pytest

from modstore_server.xiaoc_goal_management import (
    check_candidate_promotion,
    discover_goal_candidate,
    portfolio_goal_closed,
)
from modstore_server.xiaoc_life_policy import LifePolicyError


@pytest.fixture
def observation():
    now = datetime.now(UTC)
    value = {
        "status": "ok",
        "value_ledger_ready": True,
        "source_owner": "python_payment_orders",
        "observed_at": now.isoformat(),
        "window_days": 90,
        "lifecycle_gaps": {"acceptance": 3, "outcome": 1, "private": 999},
    }
    state = {"identity_id": "xiaoc", "goals": [], "policy": {}}
    return now, value, state


def test_priority_stable_identity_and_no_duplicate(observation):
    now, value, state = observation
    first, fact = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    assert first["issue_key"] == "acceptance"
    assert first["evidence_refs"] == [fact["ref"]]
    assert first["subgoals_status"] == "review_only_not_dispatched"
    assert first["cost_estimate"]["status"] == "unknown"
    assert "decision_id" not in first
    value["lifecycle_gaps"]["acceptance"] = 4
    second, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    assert first["id"] == second["id"]
    state["goals"] = [first]
    third, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    assert third["issue_key"] == "outcome"
    state["goals"].append(third)
    assert discover_goal_candidate({"customer_value": value}, state, 17, now=now) is None
    other, _ = discover_goal_candidate({"customer_value": value}, state, 18, now=now)
    assert other["id"] != first["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unknown"},
        {"value_ledger_ready": False},
        {"source_owner": "untrusted"},
        {"window_days": 1},
        {"observed_at": "2020-01-01T00:00:00Z"},
        {"lifecycle_gaps": {"acceptance": True}},
        {"lifecycle_gaps": {"acceptance": 0}},
    ],
)
def test_no_candidate_for_unverified_or_empty_evidence(observation, changes):
    now, value, state = observation
    assert discover_goal_candidate({"customer_value": {**value, **changes}}, state, 17, now=now) is None


def test_existing_promotion_checks_owner_current_gap_and_expiry(observation):
    now, value, state = observation
    goal, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    limits = {"expires_at": (now + timedelta(days=1)).isoformat()}
    check_candidate_promotion(goal, 17, limits, value, now=now)
    with pytest.raises(LifePolicyError):
        check_candidate_promotion(goal, 18, limits, value, now=now)
    with pytest.raises(LifePolicyError):
        check_candidate_promotion(goal, 17, limits, {**value, "lifecycle_gaps": {}}, now=now)
    with pytest.raises(LifePolicyError):
        check_candidate_promotion(
            goal, 17, {"expires_at": (now + timedelta(days=8)).isoformat()}, value, now=now
        )


def test_closed_portfolio_is_not_dispatchable(observation):
    now, _, _ = observation
    for status in ("rejected", "withdrawn"):
        assert portfolio_goal_closed({"status": status}, now=now)
    assert portfolio_goal_closed({"halted": True}, now=now)
    assert portfolio_goal_closed({"limits": {"expires_at": now.isoformat()}}, now=now)
    assert not portfolio_goal_closed(
        {"status": "approved", "limits": {"expires_at": (now + timedelta(days=1)).isoformat()}},
        now=now,
    )
