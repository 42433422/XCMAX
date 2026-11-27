"""Requested SLO windows and elapsed-time boundaries using the existing evidence fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.test_utils.test_production_slo_evidence import (
    _collect,
    _complete_observation,
    _rewrite_record,
    _verifier_module,
)


@pytest.mark.parametrize("window,passed", [("30d", True), ("90d", False)])
def test_thirty_day_gate_requires_its_own_prometheus_window(tmp_path, monkeypatch, window, passed):
    _complete_observation(tmp_path, monkeypatch, count=30, window=window)
    result = _verifier_module().verify_window(
        tmp_path,
        release_id="release-a",
        required_days=30,
        now=datetime(2026, 11, 30, 12, tzinfo=UTC),
    )
    assert result["passed"] is passed
    assert result["window"] == "30d" and result["required_days"] == 30
    assert result["continuous_days"] == 30
    assert result["continuous_seconds"] == 30 * 86400
    assert result["observation_start_at"] == "2026-10-31T12:00:00+00:00"
    if not passed:
        assert "final_30d_sample_evidence_missing" in result["blockers"]


@pytest.mark.parametrize("field", ["promql", "sample_promql"])
def test_thirty_day_claim_cannot_reuse_other_range_queries(tmp_path, monkeypatch, field):
    collector = _complete_observation(tmp_path, monkeypatch, count=30, window="30d")
    queries = collector.QUERIES if field == "promql" else collector.SAMPLE_QUERIES
    _rewrite_record(
        tmp_path / "029.json",
        collector,
        lambda row: row["readings"]["SLO-API-01"].update(
            {field: queries["SLO-API-01"].format(w="90d")}
        ),
    )
    result = _verifier_module().verify_window(
        tmp_path,
        release_id="release-a",
        required_days=30,
        now=datetime(2026, 11, 30, 12, tzinfo=UTC),
    )
    assert result["passed"] is False
    assert result["continuous_days"] == 0
    assert not any("hash" in blocker for blocker in result["blockers"])


@pytest.mark.parametrize(
    "required_days", [0, -1, 30.0, 30.5, True, False, float("nan"), float("inf"), "30", None]
)
def test_formal_window_requires_positive_integer_days(tmp_path, required_days):
    with pytest.raises(ValueError, match="positive observation length"):
        _verifier_module().verify_window(
            tmp_path, release_id="release-a", required_days=required_days
        )


@pytest.mark.parametrize("days", [30, 90])
@pytest.mark.parametrize(
    "shift,passed",
    [
        (timedelta(microseconds=-1), False),
        (timedelta(microseconds=1), True),
        (timedelta(seconds=15), True),
        (timedelta(seconds=15, microseconds=1), False),
    ],
)
def test_collection_jitter_uses_existing_scrape_resolution(
    tmp_path, monkeypatch, days, shift, passed
):
    window = f"{days}d"
    collector = _complete_observation(tmp_path, monkeypatch, count=days - 1, window=window)
    end = datetime(2026, 11, 1, 12, tzinfo=UTC) + timedelta(days=days - 1) + shift
    _collect(collector, tmp_path / f"{days - 1:03d}.json", window=window, now=end)
    options = {"required_days": 30} if days == 30 else {}
    result = _verifier_module().verify_window(
        tmp_path, release_id="release-a", now=end + timedelta(hours=1), **options
    )
    assert result["continuous_days"] == days
    assert result["passed"] is passed
    assert result["max_collection_gap_allowed_seconds"] == collector.SCRAPE_INTERVAL_SECONDS
    assert result["max_collection_gap_allowed_seconds"] == 15
    if shift > timedelta():
        assert result["collection_gaps"][-1]["seconds"] == shift.total_seconds()
    else:
        assert result["collection_gaps"] == []
    if not passed:
        assert result["continuous_seconds"] < days * 86400
        assert any(
            blocker.startswith("formal_continuous_seconds:") for blocker in result["blockers"]
        )
