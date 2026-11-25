"""Regression: valid-digest historical observations cannot be reordered into stale facts."""

import hashlib
import json

import pytest

from app.domain.enterprise_cognition.world_observation import (
    historical_observation,
    read_observations,
    record_observation,
)

_SCOPE = {
    "tenant_id": "11",
    "actor_id": "1",
    "mod_id": "",
    "entity_type": "order",
    "entity_id": "101",
    "source": "sales_orders",
    "read_only": True,
}


def _snapshot(remaining: str, observed_at: str) -> dict:
    authority = {
        "state": {"remaining_quantity": remaining},
        "source_last_changed": "2026-11-25T00:00:00+00:00",
    }
    digest = hashlib.sha256(
        json.dumps(
            authority, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return {
        **_SCOPE,
        **authority,
        "freshness": "fresh",
        "source_version": "sha256:" + digest,
        "observed_at": observed_at,
        "evidence": [{"source": "sales_orders", "content_sha256": digest}],
    }


def test_out_of_order_valid_digest_history_fails_closed() -> None:
    first_at = "2026-11-25T00:00:00+00:00"
    second_at = "2026-11-25T00:01:00+00:00"
    stored, _ = record_observation(None, _snapshot("8", first_at))
    stored, conflict = record_observation(json.dumps(stored), _snapshot("5", second_at))
    assert conflict is False
    healthy = historical_observation(json.dumps(stored), second_at, _SCOPE)
    assert healthy["knowledge_kind"] == "fact"
    assert healthy["observation"]["state"]["remaining_quantity"] == "5"

    reordered = {
        **stored,
        "_observation_history": list(reversed(stored["_observation_history"])),
    }
    raw = json.dumps(reordered)
    with pytest.raises(ValueError, match="observation_history_out_of_order"):
        read_observations(raw, _SCOPE)
    with pytest.raises(ValueError, match="observation_history_out_of_order"):
        historical_observation(raw, second_at, _SCOPE)


def test_same_time_conflicting_versions_remain_review_only() -> None:
    instant = "2026-11-25T00:00:00+00:00"
    stored, _ = record_observation(None, _snapshot("8", instant))
    stored, conflict = record_observation(json.dumps(stored), _snapshot("5", instant))
    assert conflict is True
    history = historical_observation(json.dumps(stored), instant, _SCOPE)
    assert history["knowledge_kind"] == "unknown"
    assert history["reason_code"] == "conflicting_observations"


def test_replayed_older_observation_does_not_replace_current_fact() -> None:
    first_at = "2026-11-25T00:00:00+00:00"
    second_at = "2026-11-25T00:01:00+00:00"
    stored, _ = record_observation(None, _snapshot("8", first_at))
    stored, _ = record_observation(json.dumps(stored), _snapshot("5", second_at))
    original = json.dumps(stored, sort_keys=True)

    replayed, rejected = record_observation(
        json.dumps(stored), _snapshot("8", first_at)
    )
    assert rejected is True
    assert json.dumps(replayed, sort_keys=True) == original
    history, _ = read_observations(json.dumps(replayed), _SCOPE)
    assert len(history) == 2
    assert replayed["state"]["remaining_quantity"] == "5"


def test_current_envelope_cannot_replay_older_valid_history_item() -> None:
    first = "2026-11-25T00:00:00+00:00"
    second = "2026-11-25T00:01:00+00:00"
    stored, _ = record_observation(None, _snapshot("8", first))
    stored, _ = record_observation(json.dumps(stored), _snapshot("5", second))
    swapped = {
        **stored["_observation_history"][0],
        "_observation_history": stored["_observation_history"],
    }
    with pytest.raises(ValueError, match="current_observation_history_mismatch"):
        read_observations(json.dumps(swapped), _SCOPE)


def test_duplicate_event_and_forged_provenance_fail_closed() -> None:
    instant = "2026-11-25T00:00:00+00:00"
    stored, _ = record_observation(None, _snapshot("8", instant))
    repeated, conflict = record_observation(json.dumps(stored), _snapshot("8", instant))
    assert conflict is False
    assert repeated["_observation_history"] == stored["_observation_history"]

    replay = _snapshot("8", instant)
    replay["evidence"][0]["event_id"] = "forged-replay-provenance"
    preserved, rejected = record_observation(json.dumps(stored), replay)
    assert rejected is True
    assert preserved == stored

    duplicated = {**stored, "_observation_history": stored["_observation_history"] * 2}
    with pytest.raises(ValueError, match="observation_duplicate_history_entry"):
        read_observations(json.dumps(duplicated), _SCOPE)

    forgery = json.loads(json.dumps(stored))
    forgery["_observation_history"][0]["evidence"][0]["source"] = "foreign_table"
    with pytest.raises(ValueError, match="observation_source_evidence_mismatch"):
        read_observations(json.dumps(forgery), _SCOPE)

    with pytest.raises(ValueError, match="observation_scope_mismatch"):
        read_observations(json.dumps(stored), {**_SCOPE, "tenant_id": "22"})


def test_history_is_not_authoritative_after_business_revocation() -> None:
    instant = "2026-11-25T00:00:00+00:00"
    stored, _ = record_observation(None, _snapshot("8", instant))
    historical = historical_observation(json.dumps(stored), instant, _SCOPE)
    assert historical["knowledge_kind"] == "fact"
    assert historical["business_validity_verified"] is False
    assert historical["current_state_verified"] is False
    # A historical observation is evidence of what was seen, not proof of a
    # currently active/authorized ERP row or an irreversible business action.
