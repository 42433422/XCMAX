"""E01-E10 focused, fail-closed governance regression checks.

These tests do not claim a production business improvement or substitute for
real independent customer / financial acceptance.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from modstore_server.xiaoc_goal_governance import (
    goal_conflicts,
    goal_dependency_gate,
    goal_path,
    governance_gate,
    observed_priority,
    project_goal_governance,
    review_milestones,
)
from modstore_server.xiaoc_goal_management import discover_goal_candidate
from modstore_server.xiaoc_life_policy import LifePolicyError
from modstore_server import xiaoc_life_store


@pytest.fixture
def operating():
    now = datetime.now(UTC)
    value = {
        "status": "ok",
        "value_ledger_ready": True,
        "source_owner": "python_payment_orders",
        "observed_at": now.isoformat(),
        "window_days": 90,
        "lifecycle_gaps": {"acceptance": 4, "outcome": 2},
    }
    state = {
        "identity_id": "xcmax:management:xiaoc",
        "mission": "有授权地改善真实客户交付",
        "goals": [],
        "policy": {},
        "paused": False,
        "owner_user_id": 17,
        "revision": 4,
    }
    goal, fact = discover_goal_candidate({"customer_value": value}, state, 17, now=now)
    state["goals"] = [goal]
    return now, value, state, goal, fact


def test_hierarchy_is_stable_across_same_quarter_and_exposes_derived_anchors(operating):
    now, _, state, goal, _ = operating
    path = goal["hierarchy"]
    assert [row["level"] for row in path["levels"]] == ["strategy", "quarter", "operating"]
    assert path["levels"][1]["parent_id"] == path["levels"][0]["id"]
    assert path["levels"][2]["parent_id"] == path["levels"][1]["id"]
    assert path["levels"][2]["id"] == goal["id"]
    assert "not_separate_approved_target" in path["levels"][1]["authority"]
    assert path == goal_path(state["identity_id"], state["mission"], goal["id"], now=now)
    assert goal_path(state["identity_id"], "另一个使命", goal["id"], now=now) != path


def test_priority_uses_only_observed_gap_and_freshness_not_invented_money(operating):
    now, value, _, goal, _ = operating
    assert goal["priority"]["benefit_proxy"]["count"] == 4
    assert goal["priority"]["risk"]["cost_not_measured"] is True
    assert "not_financial_roi" in goal["priority"]["scope"]
    smaller = observed_priority("acceptance", 2, value["observed_at"], now=now)
    assert goal["priority"]["score"] > smaller["score"]
    older = observed_priority(
        "acceptance", 4, (now - timedelta(hours=3)).isoformat(), now=now
    )
    assert goal["priority"]["score"] > older["score"]
    for invalid_count in (True, 0, -1):
        with pytest.raises(ValueError):
            observed_priority("acceptance", invalid_count, value["observed_at"], now=now)
    with pytest.raises(ValueError):
        observed_priority("acceptance", 4, "2020-01-01T00:00:00+00:00", now=now)


def test_milestones_are_ordered_review_only_and_timeout_visible(operating):
    now, _, state, goal, _ = operating
    rows = goal["milestones"]
    assert [row["step_id"] for row in rows] == ["inspect", "plan", "verify"]
    assert [row["depends_on"] for row in rows] == [[], ["inspect"], ["plan"]]
    assert all(row["scope"].startswith("review_checkpoint") for row in rows)
    assert [row["due_at"] for row in rows] == sorted(row["due_at"] for row in rows)
    future = now + timedelta(days=4)
    projection = project_goal_governance(state, now=future)["items"][0]
    assert projection["milestones"][0]["overdue"] is True
    assert projection["milestones"][-1]["overdue"] is False
    state["goals"][0]["status"] = "cancelled"
    assert all(
        not row["overdue"]
        for row in project_goal_governance(state, now=future)["items"][0]["milestones"]
    )
    with pytest.raises(ValueError):
        review_milestones(now=now, deadline=now)


def test_incompatible_bounds_and_explicit_exclusion_block_without_cross_owner_leak(operating):
    now, _, _, goal, _ = operating
    opposite = deepcopy(goal)
    opposite["id"] = "other"
    opposite["acceptance"] = {**goal["acceptance"], "direction": "max", "target": 1}
    assert goal_conflicts(goal, [opposite], now=now) == [
        {"goal_id": "other", "reason": "incompatible_metric_bounds"}
    ]
    assert governance_gate(goal, [opposite], now=now)["status"] == "blocked_conflict"
    opposite["candidate_owner_user_id"] = 18
    assert goal_conflicts(goal, [opposite], now=now) == []
    opposite["candidate_owner_user_id"] = 17
    opposite["status"] = "cancelled"
    assert goal_conflicts(goal, [opposite], now=now) == []
    opposite["status"] = "proposed"
    opposite["review_deadline"] = (now - timedelta(seconds=1)).isoformat()
    assert goal_conflicts(goal, [opposite], now=now) == []
    opposite["review_deadline"] = goal["review_deadline"]
    opposite["acceptance"] = dict(goal["acceptance"])
    opposite["excludes_goal_ids"] = [goal["id"]]
    assert goal_conflicts(goal, [opposite], now=now)[0]["reason"] == "explicit_mutual_exclusion"


def test_candidate_source_and_success_condition_cannot_be_silently_rewritten(operating):
    now, _, state, goal, _ = operating
    assert governance_gate(goal, state["goals"], now=now)["status"] == "reviewable"
    for field, changed in (
        ("acceptance", {**goal["acceptance"], "target": 1}),
        ("evidence_refs", ["customer-value-gap:" + "a" * 64]),
        ("observation", {**goal["observation"], "source_owner": "untrusted"}),
    ):
        corrupted = {**goal, field: changed}
        assert governance_gate(corrupted, [corrupted], now=now)["status"] == (
            "blocked_invalid_candidate"
        )
    assert governance_gate(
        {**goal, "review_deadline": (now - timedelta(seconds=1)).isoformat()},
        state["goals"],
        now=now,
    )["status"] == "blocked_invalid_candidate"


def test_dependencies_require_original_independent_receipts(operating):
    _, _, state, goal, _ = operating
    predecessor = deepcopy(goal)
    predecessor["id"] = "approved-predecessor"
    goal["depends_on_goal_ids"] = ["approved-predecessor"]
    assert goal_dependency_gate(goal, state["goals"])["status"] == "blocked"
    predecessor["status"] = "completed"
    assert goal_dependency_gate(goal, [predecessor])["status"] == "waiting"
    predecessor["step_projection"] = {
        "all_steps_verified": True,
        "independent_acceptance": "pending_fixed_cohort_verification",
    }
    assert goal_dependency_gate(goal, [predecessor])["status"] == "waiting"
    predecessor["step_projection"]["independent_acceptance"] = "verified_all_accepted"
    assert goal_dependency_gate(goal, [predecessor])["status"] == "ready"
    goal["depends_on_goal_ids"] = [goal["id"]]
    assert goal_dependency_gate(goal, [predecessor])["status"] == "blocked"
    goal["depends_on_goal_ids"] = ["approved-predecessor", "approved-predecessor"]
    assert goal_dependency_gate(goal, [predecessor])["status"] == "blocked"


def test_read_only_governance_projection_does_not_approve_or_mutate(operating):
    now, _, state, goal, _ = operating
    original = deepcopy(state)
    projection = project_goal_governance(state, now=now)
    assert state == original
    assert projection["items"][0]["governance"]["status"] == "reviewable"
    assert projection["items"][0]["governance"]["authorization"] == (
        "requires_existing_human_portfolio_approval"
    )
    assert projection["items"][0]["governance"]["independent_business_effect"] == "unverified"
    assert goal.get("decision_id") is None


def test_candidate_management_revision_events_and_never_cancels_bound_execution(
    operating, monkeypatch
):
    now, value, state, goal, _ = operating
    events = []

    def transact(callback):
        callback(state, object())

    monkeypatch.setattr(xiaoc_life_store, "_mutate", transact)
    monkeypatch.setattr(xiaoc_life_store, "_active_principal", lambda session, uid: uid == 17)
    monkeypatch.setattr(xiaoc_life_store, "_event", lambda session, eid, **kw: events.append((eid, kw)))
    monkeypatch.setattr(xiaoc_life_store, "read_state", lambda: deepcopy(state))
    from modstore_server import strategy_business_context

    monkeypatch.setattr(strategy_business_context, "customer_value_context", lambda: value)

    res = xiaoc_life_store.manage_operating_goal(
        goal["id"], action="pause", actor_user_id=17, expected_revision=4, reason="人工复核"
    )
    assert res["goals"][0]["status"] == "paused" and res["revision"] == 5
    assert events[-1][1]["details"]["previous"]["status"] == "proposed"
    with pytest.raises(LifePolicyError):
        xiaoc_life_store.manage_operating_goal(
            goal["id"], action="pause", actor_user_id=17, expected_revision=4, reason="过期重试"
        )
    res = xiaoc_life_store.manage_operating_goal(
        goal["id"], action="resume", actor_user_id=17, expected_revision=5, reason="恢复复核"
    )
    assert res["goals"][0]["status"] == "proposed" and res["revision"] == 6
    shortened = (now + timedelta(days=2)).isoformat()
    res = xiaoc_life_store.manage_operating_goal(
        goal["id"], action="adjust", actor_user_id=17, expected_revision=6,
        reason="提前复核", review_note="需独立客户验收", review_deadline=shortened,
    )
    assert res["goals"][0]["review_deadline"] == shortened
    assert events[-1][1]["details"]["current"]["review_note"] == "需独立客户验收"
    with pytest.raises(LifePolicyError):
        xiaoc_life_store.manage_operating_goal(
            goal["id"], action="adjust", actor_user_id=17, expected_revision=7,
            reason="延长期限", review_deadline=(now + timedelta(days=9)).isoformat(),
        )
    goal["decision_id"] = "approved-decision"
    with pytest.raises(LifePolicyError, match="原审批/执行"):
        xiaoc_life_store.manage_operating_goal(
            goal["id"], action="cancel", actor_user_id=17, expected_revision=7, reason="终止"
        )
    goal.pop("decision_id")
    res = xiaoc_life_store.manage_operating_goal(
        goal["id"], action="cancel", actor_user_id=17, expected_revision=7, reason="目标撤销"
    )
    assert res["goals"][0]["status"] == "cancelled"
    assert len(events) == 4
    assert len({eid for eid, _ in events}) == 4
    with pytest.raises(LifePolicyError):
        xiaoc_life_store.manage_operating_goal(
            goal["id"], action="resume", actor_user_id=17, expected_revision=8, reason="越过终态"
        )


def test_revoked_admin_or_stale_source_cannot_resume(operating, monkeypatch):
    now, value, state, goal, _ = operating
    goal["status"] = "paused"
    monkeypatch.setattr(xiaoc_life_store, "_mutate", lambda callback: callback(state, object()))
    monkeypatch.setattr(xiaoc_life_store, "_active_principal", lambda session, uid: False)
    with pytest.raises(LifePolicyError, match="管理员"):
        xiaoc_life_store.manage_operating_goal(
            goal["id"], action="resume", actor_user_id=17, expected_revision=4, reason="复核"
        )
    monkeypatch.setattr(xiaoc_life_store, "_active_principal", lambda session, uid: True)
    from modstore_server import strategy_business_context

    monkeypatch.setattr(
        strategy_business_context,
        "customer_value_context",
        lambda: {**value, "observed_at": "2020-01-01T00:00:00+00:00"},
    )
    with pytest.raises(LifePolicyError, match="经营缺口"):
        xiaoc_life_store.manage_operating_goal(
            goal["id"], action="resume", actor_user_id=17, expected_revision=4, reason="复核"
        )
