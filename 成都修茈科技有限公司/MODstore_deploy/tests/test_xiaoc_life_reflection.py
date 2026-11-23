"""Regression cases for verified reflection candidates."""
from __future__ import annotations

from copy import deepcopy

import pytest

from modstore_server.strategic_customer_outcomes import VERIFIED_DELIVERY_ATTRIBUTION
from modstore_server.strategic_portfolio import digest
from modstore_server.xiaoc_life_reflection import (
    candidate_id, candidate_refs, experience_candidate_facts, review_experiences,
)


def record(*, failed=False, value=2.0):
    target = {
        "metric_id": "revenue_monthly", "threshold": 1.0,
        "direction": "max", "window_days": 1,
    }
    start, end = "2026-11-20T10:00:00+00:00", "2026-11-21T10:00:00+00:00"
    snapshot = {
        "opportunity_id": "a", "hypothesis": target,
        "evidence": {
            "value": value, "source": "authoritative-payment",
            "basis": "attributed_verified_payments_in_approved_window",
            "evidence_sha256": "a" * 64,
        },
        "verdict": "hit" if value >= 1 else "miss",
        "window_start": start, "window_end": end, "reviewed_at": end,
    }
    snapshot["snapshot_sha256"] = digest(snapshot)
    task = {
        "status": "failed" if failed else "completed",
        "execution_receipt": {
            "ok": not failed, "status": "failed" if failed else "completed",
        },
        "result_sha256": "b" * 64, "calls": {},
        "started_at": start, "completed_at": start,
        "cost_basis": "approved_tariff_accrual", "accrued_cost_cents": 3,
    }
    return {
        "owner_user_id": 7, "decision_id": "decision-1", "proposal_sha256": "c" * 64,
        "authorization": {"user_id": 7, "actor": "admin:7", "proposal_sha256": "c" * 64},
        "opportunities": [{"opportunity_id": "a", "hypothesis": target, "cost_cents": 2}],
        "plan": {"selected": ["a"]}, "tasks": {"a": task},
        "hypothesis_outcomes": {"a": snapshot},
        "reviews": [{
            "at": end, "usage_complete": True, "observation_complete": True,
            "cost_basis": "approved_tariff_accrual_not_supplier_invoice",
            "accrued_cost_cents": 3, "hypotheses": [snapshot],
            "business": {
                "status": "verified", "attribution": VERIFIED_DELIVERY_ATTRIBUTION,
                "revenue_cents": 200, "order_refs_sha256": "d" * 64,
                "window_start": start, "window_end": end,
            },
        }],
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


@pytest.mark.parametrize("change", [
    "unknown_task", "missing_metric", "unsettled_usage", "open_window",
    "wrong_owner", "tampered_snapshot", "missing_business_proof", "stopped",
    "late_task", "unselected",
])
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
    assert result["outcome"] == "no_conclusion"
    assert candidates == []


def test_pending_candidate_identity_and_readback():
    _, candidates = review_experiences(record())
    candidate = candidates[0]
    changed = deepcopy(candidate)
    changed["business_evidence_sha256"] = "e" * 64
    assert candidate_id(candidate) == candidate_id(changed)
    event = {
        "id": candidate_id(candidate), "kind": "experience_candidate",
        "status": "pending_review", "evidence_refs": candidate_refs(candidate),
        "details": {
            "goal_id": "g1", "candidate": candidate, "candidate_sha256": digest(candidate),
        },
    }
    state = {
        "owner_user_id": 7, "events": [event, event],
        "goals": [{"id": "g1", "decision_id": "decision-1"}],
    }
    assert len(experience_candidate_facts(state)) == 1
    assert not experience_candidate_facts({**state, "owner_user_id": 8})
    assert not experience_candidate_facts({**state, "goals": []})
    event["details"]["candidate"]["actual"] = 1000
    assert not experience_candidate_facts(state)
