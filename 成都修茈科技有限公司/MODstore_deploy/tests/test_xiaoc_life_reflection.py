"""Regression cases for verified reflection candidates."""

from __future__ import annotations

from copy import deepcopy

import pytest

from modstore_server.strategic_customer_outcomes import VERIFIED_DELIVERY_ATTRIBUTION
from modstore_server.strategic_portfolio import digest
from modstore_server.xiaoc_life_reflection import (
    candidate_id,
    candidate_refs,
    experience_candidate_facts,
    review_experiences,
)
from tests.test_strategic_portfolio import database as database  # noqa: PLC0414
from tests.test_xiaoc_life_feedback import (  # noqa: PLC0414
    approved_life_portfolio as approved_life_portfolio,
)


def record(*, failed=False, value=2.0):
    target = {
        "metric_id": "revenue_monthly",
        "threshold": 1.0,
        "direction": "max",
        "window_days": 1,
    }
    start, end = "2026-11-20T10:00:00+00:00", "2026-11-21T10:00:00+00:00"
    snapshot = {
        "opportunity_id": "a",
        "hypothesis": target,
        "evidence": {
            "value": value,
            "source": "authoritative-payment",
            "basis": "attributed_verified_payments_in_approved_window",
            "evidence_sha256": "a" * 64,
        },
        "verdict": "hit" if value >= 1 else "miss",
        "window_start": start,
        "window_end": end,
        "reviewed_at": end,
    }
    snapshot["snapshot_sha256"] = digest(snapshot)
    task = {
        "status": "failed" if failed else "completed",
        "execution_receipt": {
            "ok": not failed,
            "status": "failed" if failed else "completed",
        },
        "result_sha256": "b" * 64,
        "calls": {},
        "started_at": start,
        "completed_at": start,
        "cost_basis": "approved_tariff_accrual",
        "accrued_cost_cents": 3,
    }
    return {
        "owner_user_id": 7,
        "decision_id": "decision-1",
        "proposal_sha256": "c" * 64,
        "authorization": {"user_id": 7, "actor": "admin:7", "proposal_sha256": "c" * 64},
        "opportunities": [{"opportunity_id": "a", "hypothesis": target, "cost_cents": 2}],
        "plan": {"selected": ["a"]},
        "tasks": {"a": task},
        "hypothesis_outcomes": {"a": snapshot},
        "reviews": [
            {
                "at": end,
                "usage_complete": True,
                "observation_complete": True,
                "cost_basis": "approved_tariff_accrual_not_supplier_invoice",
                "accrued_cost_cents": 3,
                "hypotheses": [snapshot],
                "business": {
                    "status": "verified",
                    "attribution": VERIFIED_DELIVERY_ATTRIBUTION,
                    "revenue_cents": 200,
                    "order_refs_sha256": "d" * 64,
                    "window_start": start,
                    "window_end": end,
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "failed,value,outcome",
    [(False, 2.0, "success"), (True, 2.0, "failure"), (False, 0.0, "failure")],
)
def test_reflection_outcome(failed, value, outcome):
    review, candidates = review_experiences(record(failed=failed, value=value))
    assert review["outcome"] == candidates[0]["outcome"] == outcome
    assert candidates[0]["cost_deviation_cents"] == 1
    assert candidates[0]["deviation_from_target"] == value - 1.0


@pytest.mark.parametrize(
    "change",
    [
        "unknown_task",
        "missing_metric",
        "unsettled_usage",
        "open_window",
        "wrong_owner",
        "tampered_snapshot",
        "missing_business_proof",
        "stopped",
        "late_task",
        "unselected",
    ],
)
def test_unknown_or_unbound_cannot_be_an_experience(change):
    row = record()
    task, review = row["tasks"]["a"], row["reviews"][0]
    if change == "unknown_task":
        task["status"] = "unknown"
    elif change == "missing_metric":
        row["hypothesis_outcomes"] = {}
    elif change == "unsettled_usage":
        task["calls"] = {"call": {"status": "reserved"}}
    elif change == "open_window":
        review["observation_complete"] = False
    elif change == "wrong_owner":
        row["authorization"]["user_id"] = 8
    elif change == "tampered_snapshot":
        review["hypotheses"][0]["evidence"]["value"] = 999
    elif change == "missing_business_proof":
        review["business"].pop("order_refs_sha256")
    elif change == "stopped":
        row["halted"] = True
    elif change == "late_task":
        task["completed_at"] = "2026-11-22T10:00:00+00:00"
    elif change == "unselected":
        row["plan"]["selected"] = ["b"]
    result, candidates = review_experiences(row)
    unknown = {"open_window", "wrong_owner", "missing_business_proof"}
    assert result["outcome"] == ("unknown" if change in unknown else "no_conclusion")
    assert candidates == []


@pytest.mark.parametrize("selected", [["a"], ["a", "b"]])
def test_duplicate_opportunity_cannot_attest_success_or_generate_experience(selected):
    row = record()
    row["plan"]["selected"] = selected
    row["opportunities"].append(deepcopy(row["opportunities"][0]))
    result, candidates = review_experiences(row)
    assert result["outcome"] == "unknown"
    assert result["candidate_count"] == 0
    assert candidates == []


@pytest.mark.parametrize("selected", [["a", "a"], "a", [["a"]], [" "]])
def test_invalid_selection_identity_remains_unknown(selected):
    row = record()
    row["plan"]["selected"] = selected
    result, candidates = review_experiences(row)
    assert result["outcome"] == "unknown"
    assert candidates == []


def test_success_requires_every_selected_identity():
    row = record()
    row["plan"]["selected"] = ["a", "b"]
    result, candidates = review_experiences(row)
    assert result["outcome"] == "no_conclusion"
    assert [candidate["opportunity_id"] for candidate in candidates] == ["a"]

    other = deepcopy(row["opportunities"][0])
    other["opportunity_id"] = "b"
    row["opportunities"].append(other)
    snapshot = deepcopy(row["hypothesis_outcomes"]["a"])
    snapshot["opportunity_id"] = "b"
    del snapshot["snapshot_sha256"]
    snapshot["snapshot_sha256"] = digest(snapshot)
    row["hypothesis_outcomes"]["b"] = snapshot
    row["reviews"][0]["hypotheses"].append(snapshot)
    row["tasks"]["b"] = deepcopy(row["tasks"]["a"])
    result, candidates = review_experiences(row)
    assert result["outcome"] == "success"
    assert {candidate["opportunity_id"] for candidate in candidates} == {"a", "b"}


def test_pending_candidate_identity_and_readback():
    _, candidates = review_experiences(record())
    candidate = candidates[0]
    changed = deepcopy(candidate)
    changed["business_evidence_sha256"] = "e" * 64
    assert candidate_id(candidate) == candidate_id(changed)
    event = {
        "id": candidate_id(candidate),
        "kind": "experience_candidate",
        "status": "pending_review",
        "evidence_refs": candidate_refs(candidate),
        "details": {
            "goal_id": "g1",
            "candidate": candidate,
            "candidate_sha256": digest(candidate),
        },
    }
    state = {
        "owner_user_id": 7,
        "events": [event, event],
        "goals": [{"id": "g1", "decision_id": "decision-1"}],
    }
    assert len(experience_candidate_facts(state)) == 1
    assert not experience_candidate_facts({**state, "owner_user_id": 8})
    assert not experience_candidate_facts({**state, "goals": []})
    event["details"]["candidate"]["actual"] = 1000
    assert not experience_candidate_facts(state)


def test_late_receipt_registers_one_pending_candidate_in_original_sql_ledger(
    approved_life_portfolio, monkeypatch
):
    from modstore_server import xiaoc_life_reconciliation as reconciliation
    from modstore_server import xiaoc_life_store as life
    from modstore_server.xiaoc_life_policy import LifeUpdate

    decision_id = approved_life_portfolio
    row = record()
    row.update(decision_id=decision_id, status="executing")
    row["reviews"][0]["observation_complete"] = False
    monkeypatch.setattr(reconciliation, "portfolio_status", lambda *_args, **_kwargs: row)
    life.update_settings(
        LifeUpdate(expected_revision=life.read_state()["revision"], paused=True),
        actor_user_id=7,
    )
    before = life.read_state()
    reconciliation.reconcile_goals()
    assert not experience_candidate_facts(life.read_state())
    row["reviews"][0]["observation_complete"] = True
    reconciliation.reconcile_goals()
    saved = life.read_state()
    candidates = [event for event in saved["events"] if event["kind"] == "experience_candidate"]
    assert len(candidates) == 1 and candidates[0]["status"] == "pending_review"
    assert saved["paused"] and saved["budget"] == before["budget"]
    assert experience_candidate_facts(saved)[0]["ref"] == candidates[0]["id"]

    # Fresh SQL sessions and duplicate/late reviews must not append another
    # candidate or apply changes to policy, budget or the original execution.
    assert reconciliation.reconcile_goals() == {"observed": 0}
    row["reviews"][0]["business"]["order_refs_sha256"] = "e" * 64
    reconciliation.reconcile_goals()
    again = life.read_state()
    assert [
        event["id"] for event in again["events"] if event["kind"] == "experience_candidate"
    ] == [candidates[0]["id"]]
    assert again["budget"] == before["budget"]


@pytest.mark.parametrize("frozen_review", [False, True])
def test_original_owner_review_and_revocation_are_idempotent(
    approved_life_portfolio, monkeypatch, database, frozen_review
):
    import json

    from sqlalchemy import select

    from modstore_server import xiaoc_life_reconciliation as reconciliation
    from modstore_server import xiaoc_life_store as life
    from modstore_server.db.strategic import StrategicDecision
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent
    from modstore_server.xiaoc_life_experience_review import review_experience
    from modstore_server.xiaoc_life_policy import LifePolicyError

    decision_id = approved_life_portfolio
    synthetic = record()
    with database() as session:
        row = session.scalar(
            select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
        )
        proposal = json.loads(row.decision_payload_json)
        proposal["opportunities"] = synthetic["opportunities"]
        if frozen_review:
            proposal["decision_review"] = {
                "schema": "xcagi.xiaoc_decision_review/v1",
                "selected_for_approval": "a",
                "options": [{"option_id": "a", "forecast": {"status": "unknown"}}],
            }
        from modstore_server.business_decision_review import proposal_content

        proposal_hash = digest(proposal_content(proposal))
        proposal["proposal_sha256"] = proposal_hash
        synthetic["proposal_sha256"] = proposal_hash
        synthetic["authorization"]["proposal_sha256"] = proposal_hash
        row.decision_payload_json = json.dumps(proposal)
        row.execution_result_json = json.dumps(
            {
                k: synthetic[k]
                for k in (
                    "authorization",
                    "proposal_sha256",
                    "plan",
                    "tasks",
                    "reviews",
                    "hypothesis_outcomes",
                )
            }
        )
        row.status = "executing"
        session.commit()
    reconciliation.reconcile_goals()
    initial = life.read_state()
    candidate = next(e for e in initial["events"] if e["kind"] == "experience_candidate")
    args = {
        "candidate_id": candidate["id"],
        "candidate_sha256": candidate["details"]["candidate_sha256"],
        "expected_revision": initial["revision"],
        "actor_user_id": 7,
    }
    assert initial["experience_review_facts"][0]["ref"] == candidate["id"]
    with pytest.raises(LifePolicyError):
        review_experience(**{**args, "actor_user_id": 8}, action="confirm")
    with pytest.raises(LifePolicyError):
        review_experience(**{**args, "candidate_sha256": "f" * 64}, action="confirm")
    confirmed = review_experience(**args, action="confirm")
    assert confirmed["status"] == "confirmed"
    assert review_experience(**args, action="confirm") == confirmed
    after = life.read_state()
    assert after["budget"] == initial["budget"]
    assert "reviewed_experience" in after["experience_review_facts"][0]

    with pytest.raises(LifePolicyError):
        review_experience(**{**args, "expected_revision": after["revision"]}, action="reject")

    # A later receipt that cannot reproduce the frozen candidate removes it
    # from recall even though its historic review remains immutable.
    with database() as session:
        row = session.scalar(
            select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
        )
        saved = json.loads(row.execution_result_json)
        saved["reviews"][-1]["observation_complete"] = False
        row.execution_result_json = json.dumps(saved)
        session.commit()
    assert not life.read_state()["experience_review_facts"]
    revoked = review_experience(**{**args, "expected_revision": after["revision"]}, action="revoke")
    assert revoked["status"] == "revoked"
    assert review_experience(**args, action="revoke") == revoked
    assert not life.read_state()["experience_review_facts"]
    with database() as session:
        reviews = list(
            session.scalars(
                select(XiaoCLifeEvent).where(XiaoCLifeEvent.kind == "experience_review")
            )
        )
    assert sorted(row.status for row in reviews) == ["confirmed", "revoked"]


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("failed", "model_returned_no_usable_result", "model"),
        ("blocked", "life_policy_changed_or_lease_lost", "permission"),
        ("blocked", "research_returned_no_sources", "tool"),
        ("failed", "OperationalError", "environment"),
        ("failed", "UnexpectedError", "unknown"),
        ("interrupted", "cycle_cancelled", "unknown"),
        ("completed", "model_returned_no_usable_result", "not_applicable"),
    ],
)
def test_life_failure_classification_is_code_based_not_inferred(status, reason, expected):
    from modstore_server.xiaoc_life_reflection import failure_classification

    result = failure_classification(status, reason)
    assert result["category"] == expected
    assert result["basis"] == "runtime_boundary_code_not_verified_root_cause"


def test_experience_scope_is_exact_and_advisory_only():
    from modstore_server.xiaoc_life_experience_review import (
        experience_scope,
        experience_scope_matches,
    )

    _, candidates = review_experiences(record())
    scope = experience_scope(candidates[0])
    assert scope is not None
    assert scope["category"] == "approved_task_with_observed_metric"
    assert experience_scope({**candidates[0], "target": float("inf")}) is None
    assert experience_scope({**candidates[0], "target": float("nan")}) is None
    hypothesis = {
        "metric_id": candidates[0]["metric_id"],
        "direction": candidates[0]["direction"],
        "threshold": candidates[0]["target"],
        "window_days": scope["window_days"],
    }
    assert experience_scope_matches(scope, hypothesis, candidates[0]["owner_user_id"])
    assert not experience_scope_matches(scope, hypothesis, candidates[0]["owner_user_id"] + 1)
    for change in (
        {"metric_id": "other"},
        {"direction": "min" if hypothesis["direction"] == "max" else "max"},
        {"threshold": hypothesis["threshold"] + 0.1},
        {"window_days": hypothesis["window_days"] + 1},
    ):
        assert not experience_scope_matches(
            scope, {**hypothesis, **change}, candidates[0]["owner_user_id"]
        )
    assert not experience_scope_matches(scope, {**hypothesis, "window_days": True}, 7)


def test_conflicting_or_incomplete_experience_history_never_reaches_cognition(monkeypatch):
    from types import SimpleNamespace

    from modstore_server import xiaoc_life_experience_review as module
    from modstore_server import xiaoc_life_store

    _, successes = review_experiences(record())
    _, failures = review_experiences(record(failed=True))
    first, second = successes[0], failures[0]
    assert first["outcome"] == "success" and second["outcome"] == "failure"
    candidate_events = [
        {
            "id": candidate_id(candidate),
            "details": {"candidate": candidate},
        }
        for candidate in (first, second)
    ]
    monkeypatch.setattr(xiaoc_life_store, "_active_principal", lambda session, owner: True)
    monkeypatch.setattr(xiaoc_life_store, "_event_dict", lambda row: row.event)
    monkeypatch.setattr(
        module, "_validated",
        lambda state, event: (
            event["details"]["candidate"],
            {"experience_candidate": {"outcome": event["details"]["candidate"]["outcome"]}},
        ),
    )
    monkeypatch.setattr(module, "_review_status", lambda session, event: "confirmed")
    monkeypatch.setattr(module, "_current_candidate", lambda session, candidate: True)

    class Session:
        def __init__(self, events):
            self.events = events

        def scalars(self, statement):
            return [SimpleNamespace(event=item) for item in self.events]

    state = {"owner_user_id": first["owner_user_id"]}
    conflicted = module.review_facts(Session(candidate_events), state)
    assert len(conflicted) == 2
    assert all("reviewed_experience" not in fact for fact in conflicted)
    assert all(
        fact["learning_assessment"]["reuse_blocker"] == "conflicting_measured_outcomes"
        for fact in conflicted
    )

    # A 21st row means the 20-row history cannot prove the absence of old conflicts.
    overflow = module.review_facts(Session([candidate_events[0]] * 21), state)
    assert len(overflow) == 2
    assert all("reviewed_experience" not in fact for fact in overflow)
    assert all(
        fact["learning_assessment"]["reuse_blocker"]
        == "unverified_or_truncated_review_history"
        for fact in overflow
    )

    eligible = module.review_facts(Session([candidate_events[0]]), state)
    assert len(eligible) == 1
    assert "reviewed_experience" in eligible[0]
    assert eligible[0]["learning_assessment"]["causal_effect"] == "not_established"
