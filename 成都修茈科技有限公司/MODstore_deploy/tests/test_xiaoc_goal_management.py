"""Operating candidate invariants; no model, employee or approval mocks required."""

from datetime import UTC, datetime, timedelta

import pytest

from modstore_server.xiaoc_goal_management import (
    candidate_gate,
    check_candidate_promotion,
    project_goal_steps,
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


def test_current_gap_gate_rechecks_source_owner_and_deadline(observation):
    now, value, state = observation
    goal, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    assert candidate_gate(goal, 17, value, now=now)["status"] == "eligible"
    assert candidate_gate(goal, 18, value, now=now)["status"] == "owner_mismatch"
    assert candidate_gate(
        goal, 17, {**value, "lifecycle_gaps": {"acceptance": 0}}, now=now
    )["status"] == "no_current_gap"
    assert candidate_gate(
        goal, 17, {**value, "lifecycle_gaps": {}}, now=now
    )["status"] == "awaiting_evidence"
    assert candidate_gate(
        goal, 17, {**value, "source_owner": "java_postgresql_internal_api"}, now=now
    )["status"] == "awaiting_evidence"
    assert candidate_gate(goal, 17, value, now=now + timedelta(days=8))["status"] == "expired"


def test_projection_uses_original_dependency_and_receipts_only(observation):
    now, value, state = observation
    goal, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    goal.update(decision_id="d1", step_bindings={"inspect": "i", "plan": "p"})
    record = {
        "decision_id": "d1",
        "owner_user_id": 17,
        "opportunities": [
            {"opportunity_id": "i", "depends_on": []},
            {"opportunity_id": "p", "depends_on": ["i"]},
        ],
        "tasks": {"i": {"status": "completed", "result_sha256": "a" * 64}},
    }
    projected = project_goal_steps(goal, record)
    assert [row["task_status"] for row in projected["steps"]] == ["completed", "pending"]
    assert projected["independent_acceptance"] == "pending_fixed_cohort_verification"
    assert project_goal_steps(goal, {**record, "owner_user_id": 18})["status"] == "binding_mismatch"
    record["opportunities"][1]["depends_on"] = []
    assert project_goal_steps(goal, record)["status"] == "binding_mismatch"


def test_allocations_use_existing_opportunity_contract_and_stable_dependencies(observation):
    from modstore_server.xiaoc_goal_management import GoalStepAllocation, build_goal_opportunities

    now, value, state = observation
    goal, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    caps = {"cost_cents": 20, "tokens": 200, "compute_seconds": 60}
    allocations = [
        GoalStepAllocation(step_id=step, employee_id="employee", cost_cents=10,
                           tokens=100, compute_seconds=30)
        for step in ("inspect", "plan")
    ]
    rows, bindings = build_goal_opportunities(goal, allocations, caps)
    assert rows[0]["opportunity_id"] == bindings["inspect"]
    assert rows[1]["depends_on"] == [bindings["inspect"]]
    assert build_goal_opportunities(goal, list(reversed(allocations)), caps) == (rows, bindings)
    with pytest.raises(LifePolicyError):
        build_goal_opportunities(goal, allocations, {**caps, "tokens": 199})
    with pytest.raises(LifePolicyError):
        build_goal_opportunities(goal, allocations[:1], caps)


def test_expired_unbound_candidate_renews_without_overwriting_history(observation):
    now, value, state = observation
    value["lifecycle_gaps"] = {"acceptance": 3}
    first, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    state["goals"] = [first]
    later = now + timedelta(days=8)
    fresh = {**value, "observed_at": later.isoformat()}
    renewed, fact = discover_goal_candidate({"customer_value": fresh}, state, 17, now=later)
    assert renewed["id"] != first["id"]
    assert renewed["supersedes_goal_id"] == first["id"]
    assert renewed["evidence_refs"] == [fact["ref"]]
    assert first["status"] == renewed["status"] == "proposed"
    assert "decision_id" not in renewed
    assert discover_goal_candidate({"customer_value": fresh}, state, 17, now=later)[0] == renewed
    with pytest.raises(LifePolicyError):
        check_candidate_promotion(
            first, 17, {"expires_at": (later + timedelta(days=1)).isoformat()}, fresh, now=later
        )
    state["goals"].append(renewed)
    assert discover_goal_candidate({"customer_value": fresh}, state, 17, now=later) is None
    latest = later + timedelta(days=8)
    third, _ = discover_goal_candidate(
        {"customer_value": {**fresh, "observed_at": latest.isoformat()}}, state, 17, now=latest
    )
    assert third["supersedes_goal_id"] == renewed["id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"decision_id": "original-proposal"},
        {"status": "rejected"},
        {"status": "withdrawn"},
        {"status": "completed"},
        {"review_deadline": "invalid"},
        {"step_bindings": {"inspect": "old-task"}},
    ],
)
def test_expired_bound_or_terminal_goal_cannot_be_reopened(observation, changes):
    now, value, state = observation
    value["lifecycle_gaps"] = {"acceptance": 3}
    first, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    state["goals"] = [{**first, **changes}]
    later = now + timedelta(days=8)
    fresh = {**value, "observed_at": later.isoformat()}
    assert discover_goal_candidate({"customer_value": fresh}, state, 17, now=later) is None


def test_renewal_requires_new_authoritative_observation(observation):
    now, value, state = observation
    value["lifecycle_gaps"] = {"acceptance": 3}
    first, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    state["goals"] = [first]
    deadline = now + timedelta(days=7)
    later = deadline + timedelta(hours=1)
    for changes in (
        {"observed_at": deadline.isoformat()},
        {"observed_at": later.isoformat(), "source_owner": "java_postgresql_internal_api"},
        {"observed_at": later.isoformat(), "lifecycle_gaps": {"acceptance": 0}},
    ):
        assert discover_goal_candidate(
            {"customer_value": {**value, **changes}}, state, 17, now=later
        ) is None


def test_operating_dependency_handoff_requires_verified_settled_original_receipt():
    from modstore_server.strategic_portfolio import PortfolioError
    from modstore_server.xiaoc_goal_management import operating_dependency_handoff

    child = {"opportunity_id": "life-step-plan", "depends_on": ["life-step-inspect"]}
    parent = {
        "status": "completed",
        "result_sha256": "a" * 64,
        "calls": {},
        "execution_receipt": {"ok": True, "status": "completed"},
    }
    tasks = {"life-step-inspect": parent}
    result, = operating_dependency_handoff(child, tasks)
    assert result["result_sha256"] == parent["result_sha256"]
    assert len(result["receipt_sha256"]) == 64
    assert result["artifact_receipts"] == []
    assert operating_dependency_handoff({"opportunity_id": "legacy"}, tasks) == []
    for changes in (
        {"status": "waiting"},
        {"result_sha256": None},
        {"calls": {"a": {"status": "unknown"}}},
        {"execution_receipt": {"ok": True, "status": "completed", "truncated": True}},
        {"execution_receipt": {"ok": True, "status": "pending"}},
    ):
        with pytest.raises(PortfolioError):
            operating_dependency_handoff(child, {"life-step-inspect": {**parent, **changes}})


def test_partial_or_unbound_handoff_is_not_verified(observation):
    from modstore_server.xiaoc_goal_management import operating_dependency_handoff

    now, value, state = observation
    goal, _ = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    goal.update(decision_id="d1", step_bindings={"inspect": "life-step-i", "plan": "life-step-p"})
    parent = {
        "status": "completed",
        "result_sha256": "a" * 64,
        "calls": {},
        "execution_receipt": {"ok": True, "status": "completed"},
    }
    child = {"opportunity_id": "life-step-p", "depends_on": ["life-step-i"]}
    record = {
        "decision_id": "d1", "owner_user_id": 17,
        "opportunities": [{"opportunity_id": "life-step-i", "depends_on": []}, child],
        "tasks": {"life-step-i": parent},
    }
    assert project_goal_steps(goal, record)["all_steps_verified"] is False
    record["tasks"]["life-step-p"] = {"status": "completed", "result_sha256": "b" * 64}
    assert project_goal_steps(goal, record)["all_steps_verified"] is False
    record["tasks"]["life-step-p"]["dependency_handoff"] = operating_dependency_handoff(
        child, record["tasks"]
    )
    assert project_goal_steps(goal, record)["all_steps_verified"] is True
    parent["execution_receipt"]["status"] = "pending"
    assert project_goal_steps(goal, record)["all_steps_verified"] is False
