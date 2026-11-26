"""Independent contracts for scoped self evidence, never LLM self-certification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import xiaoc_self_model as self_model
from modstore_server.xiaoc_life_policy import IDENTITY_ID


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv("MODSTORE_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_RELEASE_ARTIFACT_SHA256", "b" * 64)
    monkeypatch.setenv("XCMAX_PRODUCT_VERSION", "1.0.0.7")
    return {
        "identity_id": IDENTITY_ID,
        "revision": 2,
        "level": 4,
        "paused": False,
        "owner_user_id": 7,
        "self_authority_active": True,
        "policy": {
            "authorization_expires_at": "2026-12-01T00:00:00+00:00",
            "daily_token_limit": 500,
        },
        "budget": {"used_tokens": 12, "reserved_tokens": 10},
        "events": [],
    }


NOW = datetime(2026, 11, 24, tzinfo=UTC)


def proof(scope, *, checked=NOW, verdict="pass"):
    return {
        "id": "self-check:one",
        "kind": "self_identity_check",
        "status": verdict,
        "details": {
            "identity_proof": {
                "scope": scope,
                "verdict": verdict,
                "checked_at": checked.isoformat(),
            }
        },
    }


def test_identity_proof_current_only_and_narrow(state):
    scope = self_model.execution_scope(state, now=NOW)
    assert scope is not None
    evidence = self_model.current_identity_evidence(scope, [proof(scope)], now=NOW)
    assert evidence["status"] == "verified"
    assert evidence["scope"] == "persistent_identity_only"
    assert (
        self_model.current_identity_evidence(scope, [proof(scope, verdict="fail")], now=NOW)[
            "status"
        ]
        == "unavailable"
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("revision", 3),
        ("owner_user_id", 8),
        ("self_authority_active", False),
        ("level", 3),
        ("paused", True),
    ],
)
def test_policy_and_authority_change_invalidate_proof(state, key, value):
    scope = self_model.execution_scope(state, now=NOW)
    changed = self_model.execution_scope({**state, key: value}, now=NOW)
    assert scope != changed
    assert (
        self_model.current_identity_evidence(changed, [proof(scope)], now=NOW)["status"]
        == "unverified"
    )


def test_release_artifact_host_and_expiry_change_invalidate(state, monkeypatch):
    scope = self_model.execution_scope(state, now=NOW)
    assert self_model.execution_scope(state, now=NOW + timedelta(days=8)) != scope
    monkeypatch.setenv("MODSTORE_RELEASE_ARTIFACT_SHA256", "c" * 64)
    assert self_model.execution_scope(state, now=NOW) != scope
    monkeypatch.setenv("MODSTORE_GIT_SHA", "d" * 40)
    assert self_model.execution_scope(state, now=NOW) is None
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "d" * 40)
    new_scope = self_model.execution_scope(state, now=NOW)
    assert new_scope is not None and new_scope != scope
    monkeypatch.setattr(self_model.platform, "node", lambda: "different-host")
    assert self_model.execution_scope(state, now=NOW) != new_scope


def test_unbound_expired_future_and_model_hypotheses_do_not_verify(state):
    scope = self_model.execution_scope(state, now=NOW)
    assert (
        self_model.current_identity_evidence(None, [proof(scope)], now=NOW)["status"]
        == "unverified"
    )
    for checked in (NOW - timedelta(days=2), NOW + timedelta(seconds=1)):
        assert (
            self_model.current_identity_evidence(scope, [proof(scope, checked=checked)], now=NOW)[
                "status"
            ]
            == "unverified"
        )
    fake = {**proof(scope), "kind": "reflection", "status": "pass"}
    assert self_model.current_identity_evidence(scope, [fake], now=NOW)["status"] == "unverified"
    state["self_model"] = {"status": "verified", "title": "invented mastery"}
    assert (
        self_model.project(state)["self_assessment"]["status"] == "hypothesis_not_capability_proof"
    )


def test_performance_deduplicates_and_excludes_other_release_and_unknown(state):
    scope = self_model.execution_scope(state, now=NOW)

    def receipt(key, status, token, stamp):
        return {
            "id": "cycle:" + key,
            "status": status,
            "model": "provider/model",
            "actual_tokens": token,
            "details": {"execution_scope": stamp, "reason": "model_error"},
        }

    good = receipt("a", "completed", 9, scope)
    result = self_model.performance(
        scope,
        [
            good,
            good,
            receipt("b", "failed", 4, scope),
            receipt("c", "unknown", None, scope),
            receipt("d", "completed", 200, "old"),
            receipt("e", "completed", 100, None),
        ],
    )
    assert result["cycle_completion_rate"] == 0.5
    assert result["known_tokens"] == 13
    assert result["unknown_token_receipts"] == 1
    assert result["historical_or_unbound_count"] == 2
    assert result["failure_types"] == {"model_error": 1}
    assert result["cost_cents"] is None



def test_latest_identity_failure_overrides_older_success_in_any_order(state):
    scope = self_model.execution_scope(state, now=NOW)
    earlier = proof(scope, checked=NOW - timedelta(minutes=10))
    later = proof(scope, checked=NOW, verdict="fail")
    later["id"] = "self-check:later"
    for events in ([earlier, later], [later, earlier]):
        result = self_model.current_identity_evidence(scope, events, now=NOW)
        assert result["status"] == "unavailable"
        assert result["evidence_ref"] == "self-check:later"


def test_ambiguous_identity_checks_never_claim_verified(state):
    scope = self_model.execution_scope(state, now=NOW)
    passed = proof(scope)
    failed = proof(scope, verdict="fail")
    failed["id"] = "self-check:conflicting"
    result = self_model.current_identity_evidence(scope, [passed, failed], now=NOW)
    assert result == {"status": "unverified", "reason": "conflicting_identity_proofs"}
    failed["id"] = passed["id"]
    assert (
        self_model.current_identity_evidence(scope, [passed, failed], now=NOW)["status"]
        == "unverified"
    )


def test_cycle_id_conflicts_are_quarantined_from_self_success(state):
    scope = self_model.execution_scope(state, now=NOW)
    original = {
        "id": "cycle:conflict",
        "status": "completed",
        "actual_tokens": 7,
        "details": {"execution_scope": scope},
    }
    contradicted = {**original, "status": "failed", "actual_tokens": 9}
    valid = {**original, "id": "cycle:good"}
    result = self_model.performance(scope, [original, contradicted, valid, valid])
    assert result["conflicting_cycle_receipts"] == 1
    assert result["current_scope_count"] == 1
    assert result["statuses"] == {"completed": 1}
    assert result["known_tokens"] == 7

def test_promptfoo_candidate_is_historical_not_current_proof(state):
    event = {
        "id": "self-promptfoo:receipt",
        "kind": "self_promptfoo_check",
        "status": "historical_measurement",
        "details": {
            "engine": "promptfoo",
            "baseline": {"pass": 0, "total": 2},
            "candidate": {"pass": 2, "total": 2},
            "bundle_sha256": "a" * 64,
            "results_sha256": "b" * 64,
        },
    }
    state["self_promptfoo_checks"] = [event]
    result = self_model.project(state)
    assert result["identity_readback"]["status"] == "unverified"
    assert (
        result["historical_evaluations"][0]["status"]
        == "historical_measurement_not_current_capability"
    )
    assert result["historical_evaluations"][0]["candidate"]["pass"] == 2
