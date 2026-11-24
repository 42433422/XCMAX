from datetime import UTC, datetime, timedelta

import pytest

from modstore_server.xiaoc_life_world import advance_review, review_projection

DAY = datetime(2026, 11, 10, tzinfo=UTC)
METRIC = "intent_accuracy"


def observation(day, value, digest):
    return {METRIC: {
        "observed_at": (DAY + timedelta(days=day)).isoformat(),
        "value": value,
        "source_sha256": digest * 64,
    }}


def advance(previous, day, data, owner=7):
    return advance_review(previous, data, owner=owner, now=DAY + timedelta(days=day))


def two_samples():
    state = advance(None, 0, observation(0, 0.4, "a"))
    return advance(state, 1, observation(1, 0.8, "b"))


def test_forward_forecast_is_frozen_then_evaluated_once():
    state = two_samples()
    series = state["series"][METRIC]
    assert series["pending"]["expected"] == pytest.approx(0.6)
    assert series["pending"]["baseline"] == 0.8
    assert not series["evaluations"]
    # A reread of the training point cannot evaluate its own prediction.
    assert advance(state, 1, observation(1, 0.8, "b")) == state
    future = advance(state, 2, observation(2, 0.5, "c"))
    evaluated = future["series"][METRIC]["evaluations"]
    assert len(evaluated) == 1
    assert evaluated[0]["forecast"] == series["pending"]
    assert evaluated[0]["actual"]["value"] == 0.5
    projection = review_projection(future, 7)[METRIC]
    assert projection["median_mae"] == pytest.approx(0.1)
    assert projection["last_value_mae"] == pytest.approx(0.3)
    assert advance(future, 3, observation(2, 0.5, "c")) == future


def test_preissue_late_observation_cannot_score():
    first = advance(None, 1, observation(0, 0.4, "a"))
    state = advance(first, 3, observation(1, 0.8, "b"))
    late = advance(state, 4, observation(2, 0.5, "c"))
    assert not late["series"][METRIC]["evaluations"]
    assert late["series"][METRIC]["pending"] == state["series"][METRIC]["pending"]


def test_expired_forecast_is_unknown_and_not_reissued_without_new_data():
    state = two_samples()
    expired = advance(state, 9, {})
    series = expired["series"][METRIC]
    assert series["pending"] is None and series["expired"] == 1
    assert not series["evaluations"]
    assert advance(expired, 10, {}) == expired


@pytest.mark.parametrize("value,digest,day", [(True, "c", 2), (float("nan"), "c", 2), (1.2, "c", 2), (0.5, "z", 2), (0.5, "c", 3), (0.5, "a", 2), (0.5, "c", 1)])
def test_invalid_future_duplicate_or_same_timestamp_evidence_is_ignored(value, digest, day):
    state = two_samples()
    assert advance(state, 2, observation(day, value, digest)) == state


def test_owner_handoff_never_reuses_previous_forecast():
    state = two_samples()
    assert review_projection(state, 8) == {}
    new = advance(state, 2, observation(2, 0.5, "c"), owner=8)
    assert new["owner_user_id"] == 8
    assert len(new["series"][METRIC]["samples"]) == 1
    assert new["series"][METRIC]["pending"] is None


def test_forecast_rejects_inconsistent_persisted_training():
    state = two_samples()
    state["series"][METRIC]["pending"]["expected"] = 0.99
    with pytest.raises(ValueError, match="training receipt is inconsistent"):
        advance(state, 2, observation(2, 0.5, "c"))


def test_forecast_series_isolation_and_bounded_history():
    state = two_samples()
    extra = observation(2, 0.5, "c")[METRIC]
    state = advance(state, 2, {"legacy_ratio": extra})
    assert not state["series"]["legacy_ratio"]["evaluations"]
    assert state["series"][METRIC]["pending"] is not None
    for day in range(3, 16):
        raw = observation(day, 0.5, "c")
        raw[METRIC]["source_sha256"] = f"{day:064x}"
        state = advance(state, day, raw)
    series = state["series"][METRIC]
    assert len(series["samples"]) == 3
    assert len(series["evaluations"]) == 8
    assert review_projection(state, 7)[METRIC]["evaluated_count"] == 8
