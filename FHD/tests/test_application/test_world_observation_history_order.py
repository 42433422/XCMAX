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
