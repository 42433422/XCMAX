"""Tests for ``modstore_server.self_maintenance_burnin``.

Covers:
- ``compute_burnin_metrics`` (empty ledger, all merged, mixed, window filter, manual count)
- ``check_burnin_thresholds`` (4 metric breaches, multi-breach, not started)
- Phase thresholds (monotonic increase, Day 1/3/5 boundaries, expired, not started)
- ``_incident_fingerprint`` (deterministic, differs by metric, differs by phase)
- ``_should_notify_sms`` (first day no SMS, 2-day SMS, different metric no SMS, no breach)
- ``start`` / ``reset`` / ``status`` state machine
- ``run_burnin_check`` (not started, writes history, breach opens incident, expired)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from modstore_server.self_maintenance_burnin import (
    PHASE_THRESHOLDS,
    TOTAL_BURNIN_DAYS,
    ThresholdBreach,
    _incident_fingerprint,
    _should_notify_sms,
    check_burnin_thresholds,
    compute_burnin_metrics,
    get_burnin_day_index,
    get_burnin_start_at,
    get_burnin_status,
    get_current_phase_threshold,
    open_burnin_incident,
    reset_burnin,
    run_burnin_check,
    set_burnin_start_at,
    start_burnin,
)


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    """Point MODSTORE_RUNTIME_DIR at a tmp_path so all burnin files are isolated.

    Also clears any pre-existing burnin state cache. Tests should write ledger
    rows via ``_append_ledger_row`` and governance audit rows via
    ``_append_governance_review``.
    """

    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def _utc_iso(dt: datetime) -> str:
    return dt.isoformat()


def _append_ledger_row(runtime_dir: Path, row: Dict[str, Any]) -> None:
    ledger = runtime_dir / "self_maintenance_loop_runs.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _append_governance_review(runtime_dir: Path, row: Dict[str, Any]) -> None:
    path = runtime_dir / "self_maintenance_governance_actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _append_history_row(runtime_dir: Path, row: Dict[str, Any]) -> None:
    path = runtime_dir / "burnin_metrics.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _make_complete_row(
    *,
    status: str,
    completed_at: datetime,
    triggered_by: str = "scheduler",
    run_id: str = "run-1",
) -> Dict[str, Any]:
    return {
        "phase": "complete",
        "status": status,
        "completed_at": _utc_iso(completed_at),
        "started_at": _utc_iso(completed_at - timedelta(hours=1)),
        "triggered_by": triggered_by,
        "run_id": run_id,
    }


def _make_start_row(*, triggered_by: str, created_at: datetime, run_id: str) -> Dict[str, Any]:
    return {
        "phase": "start",
        "triggered_by": triggered_by,
        "created_at": _utc_iso(created_at),
        "run_id": run_id,
    }


# --------------------------------------------------------------------------- #
# compute_burnin_metrics
# --------------------------------------------------------------------------- #


def test_compute_burnin_metrics_empty_ledger_returns_zero_safe_defaults(
    isolated_runtime,
):
    metrics = compute_burnin_metrics()

    assert metrics["total_complete_runs"] == 0
    assert metrics["completed_merged"] == 0
    assert metrics["completed_merged_rate"] == 0.0
    assert metrics["waiting_human"] == 0
    assert metrics["waiting_human_rate"] == 0.0
    assert metrics["failed"] == 0
    assert metrics["abandoned_stale"] == 0
    assert metrics["health"] == 1.0
    assert metrics["manual_intervention_count"] == 0
    assert "window_start" in metrics and "window_end" in metrics


def test_compute_burnin_metrics_all_merged_rates_one(isolated_runtime):
    now = datetime.now(timezone.utc)
    for idx in range(3):
        _append_ledger_row(
            isolated_runtime,
            _make_complete_row(
                status="completed_merged",
                completed_at=now - timedelta(hours=idx),
                run_id=f"run-merged-{idx}",
            ),
        )

    metrics = compute_burnin_metrics(now=now)

    assert metrics["total_complete_runs"] == 3
    assert metrics["completed_merged"] == 3
    assert metrics["completed_merged_rate"] == 1.0
    assert metrics["waiting_human_rate"] == 0.0
    assert metrics["health"] == 1.0


def test_compute_burnin_metrics_mixed_statuses(isolated_runtime):
    now = datetime.now(timezone.utc)
    rows = [
        _make_complete_row(
            status="completed_merged",
            completed_at=now - timedelta(hours=1),
            run_id="r1",
        ),
        _make_complete_row(
            status="completed_waiting_human_strategy",
            completed_at=now - timedelta(hours=2),
            run_id="r2",
        ),
        _make_complete_row(status="failed", completed_at=now - timedelta(hours=3), run_id="r3"),
        _make_complete_row(
            status="abandoned_stale", completed_at=now - timedelta(hours=4), run_id="r4"
        ),
    ]
    for row in rows:
        _append_ledger_row(isolated_runtime, row)

    metrics = compute_burnin_metrics(now=now)

    assert metrics["total_complete_runs"] == 4
    assert metrics["completed_merged"] == 1
    assert metrics["completed_merged_rate"] == 0.25
    assert metrics["waiting_human"] == 1
    assert metrics["waiting_human_rate"] == 0.25
    assert metrics["failed"] == 1
    assert metrics["abandoned_stale"] == 1
    assert metrics["health"] == 0.5  # 1 - (1+1)/4


def test_compute_burnin_metrics_window_filter_excludes_old_rows(isolated_runtime):
    now = datetime.now(timezone.utc)
    # Recent row inside the 7-day window
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(
            status="completed_merged",
            completed_at=now - timedelta(days=1),
            run_id="recent",
        ),
    )
    # Old row outside the 7-day window
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(
            status="failed",
            completed_at=now - timedelta(days=10),
            run_id="old",
        ),
    )

    metrics = compute_burnin_metrics(now=now)

    assert metrics["total_complete_runs"] == 1
    assert metrics["completed_merged"] == 1
    assert metrics["failed"] == 0


def test_compute_burnin_metrics_manual_intervention_count(isolated_runtime):
    now = datetime.now(timezone.utc)
    # 2 manual starts + 1 scheduled start
    _append_ledger_row(
        isolated_runtime,
        _make_start_row(triggered_by="manual", created_at=now - timedelta(hours=1), run_id="m1"),
    )
    _append_ledger_row(
        isolated_runtime,
        _make_start_row(triggered_by="manual", created_at=now - timedelta(hours=2), run_id="m2"),
    )
    _append_ledger_row(
        isolated_runtime,
        _make_start_row(triggered_by="scheduler", created_at=now - timedelta(hours=3), run_id="s1"),
    )
    # 3 governance_audit reviews (only "review_governance_audit" action counts)
    for idx in range(3):
        _append_governance_review(
            isolated_runtime,
            {
                "action": "review_governance_audit",
                "created_at": _utc_iso(now - timedelta(hours=idx)),
                "ok": True,
            },
        )
    # Other governance action should not be counted
    _append_governance_review(
        isolated_runtime,
        {
            "action": "auto_merge_low_risk",
            "created_at": _utc_iso(now),
            "ok": True,
        },
    )

    metrics = compute_burnin_metrics(now=now)

    assert metrics["manual_runs"] == 2
    assert metrics["governance_reviews"] == 3
    assert metrics["manual_intervention_count"] == 5


# --------------------------------------------------------------------------- #
# check_burnin_thresholds
# --------------------------------------------------------------------------- #


def _seed_burnin_started(days_ago: int = 0) -> datetime:
    """Start burnin ``days_ago`` days before now. Returns the start datetime."""

    start = datetime.now(timezone.utc) - timedelta(days=days_ago)
    set_burnin_start_at(started_by="test")
    # Override state with a precise start time for deterministic day indexing.
    from modstore_server.self_maintenance_burnin import _save_burnin_state

    _save_burnin_state(
        {
            "started_at": start.isoformat(),
            "started_by": "test",
            "reset_history": [],
        }
    )
    return start


def test_check_burnin_thresholds_completed_merged_breach(isolated_runtime):
    now = datetime.now(timezone.utc)
    _seed_burnin_started(days_ago=0)  # Day 1 → threshold 0.30
    # 2 waiting_human + 1 merged → completed_merged_rate = 1/3 < 0.30? 0.33 > 0.30, no breach
    # Use 5 waiting + 1 merged → 1/6 ≈ 0.17 < 0.30 → breach
    for idx in range(5):
        _append_ledger_row(
            isolated_runtime,
            _make_complete_row(
                status="completed_waiting_human_strategy",
                completed_at=now - timedelta(hours=idx),
                run_id=f"wh-{idx}",
            ),
        )
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(status="completed_merged", completed_at=now, run_id="merged-1"),
    )

    breaches, _ = check_burnin_thresholds(now=now)

    metrics_breached = {b.metric for b in breaches}
    assert "completed_merged_rate" in metrics_breached
    assert all(b.day_range == "Day 1-2" for b in breaches)


def test_check_burnin_thresholds_waiting_human_breach(isolated_runtime):
    now = datetime.now(timezone.utc)
    _seed_burnin_started(days_ago=0)  # Day 1 → waiting_human_max=0.70
    # 4 waiting_human + 1 merged → waiting_human_rate = 4/5 = 0.80 > 0.70
    for idx in range(4):
        _append_ledger_row(
            isolated_runtime,
            _make_complete_row(
                status="completed_waiting_human_strategy",
                completed_at=now - timedelta(hours=idx),
                run_id=f"wh-{idx}",
            ),
        )
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(status="completed_merged", completed_at=now, run_id="merged-1"),
    )

    breaches, _ = check_burnin_thresholds(now=now)

    metrics_breached = {b.metric for b in breaches}
    assert "waiting_human_rate" in metrics_breached


def test_check_burnin_thresholds_health_breach(isolated_runtime):
    now = datetime.now(timezone.utc)
    _seed_burnin_started(days_ago=0)  # Day 1 → health_min=0.50
    # 3 failed + 1 merged → health = 1 - 3/4 = 0.25 < 0.50
    for idx in range(3):
        _append_ledger_row(
            isolated_runtime,
            _make_complete_row(
                status="failed",
                completed_at=now - timedelta(hours=idx),
                run_id=f"fail-{idx}",
            ),
        )
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(status="completed_merged", completed_at=now, run_id="merged-1"),
    )

    breaches, _ = check_burnin_thresholds(now=now)

    metrics_breached = {b.metric for b in breaches}
    assert "health" in metrics_breached


def test_check_burnin_thresholds_manual_intervention_breach(isolated_runtime):
    now = datetime.now(timezone.utc)
    _seed_burnin_started(days_ago=0)  # Day 1 → manual_max=5
    # 6 manual runs → manual_intervention_count = 6 > 5
    for idx in range(6):
        _append_ledger_row(
            isolated_runtime,
            _make_start_row(
                triggered_by="manual",
                created_at=now - timedelta(hours=idx),
                run_id=f"m-{idx}",
            ),
        )

    breaches, _ = check_burnin_thresholds(now=now)

    metrics_breached = {b.metric for b in breaches}
    assert "manual_intervention_count" in metrics_breached


def test_check_burnin_thresholds_multiple_breaches(isolated_runtime):
    now = datetime.now(timezone.utc)
    _seed_burnin_started(days_ago=0)  # Day 1 thresholds
    # Construct a ledger that breaches both health and completed_merged_rate
    # 3 failed + 1 waiting_human → total=4, merged=0, failed=3, health=0.25
    for idx in range(3):
        _append_ledger_row(
            isolated_runtime,
            _make_complete_row(
                status="failed",
                completed_at=now - timedelta(hours=idx),
                run_id=f"fail-{idx}",
            ),
        )
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(
            status="completed_waiting_human_strategy",
            completed_at=now,
            run_id="wh-1",
        ),
    )

    breaches, _ = check_burnin_thresholds(now=now)

    metrics_breached = {b.metric for b in breaches}
    assert "completed_merged_rate" in metrics_breached  # 0/4 = 0.0 < 0.30
    assert "health" in metrics_breached  # 1 - 3/4 = 0.25 < 0.50


def test_check_burnin_thresholds_not_started_returns_empty(isolated_runtime):
    now = datetime.now(timezone.utc)
    # Don't call _seed_burnin_started

    breaches, notify_sms = check_burnin_thresholds(now=now)

    assert breaches == []
    assert notify_sms is False


# --------------------------------------------------------------------------- #
# Phase thresholds
# --------------------------------------------------------------------------- #


def test_phase_thresholds_monotonically_increase(isolated_runtime):
    # completed_merged_min must increase across phases
    mins = [t.completed_merged_min for t in PHASE_THRESHOLDS]
    assert mins == sorted(mins)
    assert mins[0] < mins[-1]
    # health_min must increase
    healths = [t.health_min for t in PHASE_THRESHOLDS]
    assert healths == sorted(healths)
    # waiting_human_max must decrease (tighter)
    wh = [t.waiting_human_max for t in PHASE_THRESHOLDS]
    assert wh == sorted(wh, reverse=True)
    # manual_max must decrease
    mm = [t.manual_max for t in PHASE_THRESHOLDS]
    assert mm == sorted(mm, reverse=True)


def test_phase_threshold_day1_returns_first_phase(isolated_runtime):
    _seed_burnin_started(days_ago=0)  # day 1

    threshold = get_current_phase_threshold()

    assert threshold is not None
    assert threshold.label == "Day 1-2"


def test_phase_threshold_day3_returns_second_phase(isolated_runtime):
    _seed_burnin_started(days_ago=2)  # day 3

    threshold = get_current_phase_threshold()

    assert threshold is not None
    assert threshold.label == "Day 3-4"


def test_phase_threshold_day5_returns_third_phase(isolated_runtime):
    _seed_burnin_started(days_ago=4)  # day 5

    threshold = get_current_phase_threshold()

    assert threshold is not None
    assert threshold.label == "Day 5-7"


def test_phase_threshold_expired_returns_none(isolated_runtime):
    _seed_burnin_started(days_ago=TOTAL_BURNIN_DAYS)  # day 8

    threshold = get_current_phase_threshold()

    assert threshold is None


def test_phase_threshold_not_started_returns_none(isolated_runtime):
    threshold = get_current_phase_threshold()

    assert threshold is None


# --------------------------------------------------------------------------- #
# _incident_fingerprint
# --------------------------------------------------------------------------- #


def test_incident_fingerprint_deterministic(isolated_runtime):
    breach = ThresholdBreach(
        metric="health",
        actual=0.3,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )

    fp1 = _incident_fingerprint(breach, "Day 1-2")
    fp2 = _incident_fingerprint(breach, "Day 1-2")

    assert fp1 == fp2
    assert len(fp1) == 32  # sha256 truncated to 32 hex chars


def test_incident_fingerprint_differs_by_metric(isolated_runtime):
    breach_a = ThresholdBreach(
        metric="health",
        actual=0.3,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )
    breach_b = ThresholdBreach(
        metric="completed_merged_rate",
        actual=0.2,
        threshold=0.3,
        direction="below_min",
        day_range="Day 1-2",
    )

    fp_a = _incident_fingerprint(breach_a, "Day 1-2")
    fp_b = _incident_fingerprint(breach_b, "Day 1-2")

    assert fp_a != fp_b


def test_incident_fingerprint_differs_by_phase(isolated_runtime):
    breach = ThresholdBreach(
        metric="health",
        actual=0.3,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )

    fp_phase1 = _incident_fingerprint(breach, "Day 1-2")
    fp_phase3 = _incident_fingerprint(breach, "Day 3-4")

    assert fp_phase1 != fp_phase3


def test_incident_fingerprint_ignores_actual(isolated_runtime):
    """Same metric + day_range but different actual → same fingerprint (dedup)."""

    breach_a = ThresholdBreach(
        metric="health",
        actual=0.1,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )
    breach_b = ThresholdBreach(
        metric="health",
        actual=0.4,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )

    assert _incident_fingerprint(breach_a, "Day 1-2") == _incident_fingerprint(breach_b, "Day 1-2")


# --------------------------------------------------------------------------- #
# _should_notify_sms
# --------------------------------------------------------------------------- #


def test_should_notify_sms_first_day_no_sms(isolated_runtime):
    _seed_burnin_started(days_ago=0)  # day 1
    breach = ThresholdBreach(
        metric="health",
        actual=0.3,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )

    # No prior history → no SMS even with breach
    assert _should_notify_sms([breach], PHASE_THRESHOLDS[0]) is False


def test_should_notify_sms_consecutive_two_days(isolated_runtime):
    _seed_burnin_started(days_ago=1)  # day 2 (prior day = day 1)
    # Seed history: day 1 had a health breach
    _append_history_row(
        isolated_runtime,
        {
            "burnin_day": 1,
            "phase": "Day 1-2",
            "breaches": [
                {
                    "metric": "health",
                    "actual": 0.2,
                    "threshold": 0.5,
                    "direction": "below_min",
                    "day_range": "Day 1-2",
                }
            ],
            "notify_sms": False,
            "timestamp": _utc_iso(datetime.now(timezone.utc) - timedelta(days=1)),
        },
    )

    breach = ThresholdBreach(
        metric="health",
        actual=0.3,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )

    assert _should_notify_sms([breach], PHASE_THRESHOLDS[0]) is True


def test_should_notify_sms_different_metric_no_sms(isolated_runtime):
    _seed_burnin_started(days_ago=1)  # day 2
    # Day 1 had a health breach
    _append_history_row(
        isolated_runtime,
        {
            "burnin_day": 1,
            "phase": "Day 1-2",
            "breaches": [
                {
                    "metric": "health",
                    "actual": 0.2,
                    "threshold": 0.5,
                    "direction": "below_min",
                    "day_range": "Day 1-2",
                }
            ],
            "notify_sms": False,
            "timestamp": _utc_iso(datetime.now(timezone.utc) - timedelta(days=1)),
        },
    )

    # Today: only completed_merged_rate breaches (different metric)
    breach = ThresholdBreach(
        metric="completed_merged_rate",
        actual=0.1,
        threshold=0.3,
        direction="below_min",
        day_range="Day 1-2",
    )

    assert _should_notify_sms([breach], PHASE_THRESHOLDS[0]) is False


def test_should_notify_sms_no_breach_no_sms(isolated_runtime):
    _seed_burnin_started(days_ago=1)
    _append_history_row(
        isolated_runtime,
        {
            "burnin_day": 1,
            "phase": "Day 1-2",
            "breaches": [
                {
                    "metric": "health",
                    "actual": 0.2,
                    "threshold": 0.5,
                    "direction": "below_min",
                    "day_range": "Day 1-2",
                }
            ],
            "notify_sms": False,
            "timestamp": _utc_iso(datetime.now(timezone.utc) - timedelta(days=1)),
        },
    )

    # Today: no breaches
    assert _should_notify_sms([], PHASE_THRESHOLDS[0]) is False


# --------------------------------------------------------------------------- #
# start / reset / status state machine
# --------------------------------------------------------------------------- #


def test_start_burnin_sets_active_state(isolated_runtime):
    result = start_burnin(started_by="admin")

    assert result["ok"] is True
    assert result["active"] is True
    assert result["burnin_day"] == 1
    assert result["phase"] == "Day 1-2"
    assert result["started_by"] == "admin"
    assert get_burnin_start_at() is not None


def test_start_burnin_twice_returns_error(isolated_runtime):
    start_burnin(started_by="admin")
    result = start_burnin(started_by="admin")

    assert result["ok"] is False
    assert result["active"] is True
    assert "error" in result
    assert "already started" in result["error"]


def test_reset_burnin_clears_state_and_preserves_history(isolated_runtime):
    start_burnin(started_by="admin")
    reset_result = reset_burnin(reset_by="ops")

    assert reset_result["ok"] is True
    assert reset_result["active"] is False
    assert len(reset_result["reset_history"]) == 1
    assert reset_result["reset_history"][0]["started_by"] == "admin"
    assert reset_result["reset_history"][0]["reset_by"] == "ops"
    assert get_burnin_start_at() is None


def test_get_burnin_status_not_started(isolated_runtime):
    status = get_burnin_status()

    assert status["active"] is False
    assert status["started_at"] is None
    assert status["burnin_day"] == 0
    assert status["phase"] is None


def test_get_burnin_status_active(isolated_runtime):
    start_burnin(started_by="admin")

    status = get_burnin_status()

    assert status["active"] is True
    assert status["expired"] is False
    assert status["burnin_day"] == 1
    assert status["phase"] == "Day 1-2"
    assert status["remaining_days"] == TOTAL_BURNIN_DAYS


def test_get_burnin_status_expired(isolated_runtime):
    _seed_burnin_started(days_ago=TOTAL_BURNIN_DAYS)  # day 8 → expired

    status = get_burnin_status()

    assert status["active"] is False
    assert status["expired"] is True
    assert status["burnin_day"] == TOTAL_BURNIN_DAYS + 1
    assert status["phase"] is None
    assert status["remaining_days"] == 0


# --------------------------------------------------------------------------- #
# run_burnin_check
# --------------------------------------------------------------------------- #


def test_run_burnin_check_not_started_returns_not_started(isolated_runtime):
    result = run_burnin_check()

    assert result["ok"] is False
    assert result["active"] is False
    assert result["reason"] == "not_started"


def test_run_burnin_check_writes_history(isolated_runtime):
    _seed_burnin_started(days_ago=0)  # day 1
    # All merged → no breaches
    now = datetime.now(timezone.utc)
    _append_ledger_row(
        isolated_runtime,
        _make_complete_row(status="completed_merged", completed_at=now, run_id="r1"),
    )

    result = run_burnin_check(now=now)

    assert result["ok"] is True
    assert result["active"] is True
    assert result["burnin_day"] == 1
    assert result["breaches"] == []

    history_path = isolated_runtime / "burnin_metrics.jsonl"
    assert history_path.exists()
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["burnin_day"] == 1
    assert entry["phase"] == "Day 1-2"
    assert entry["breaches"] == []
    assert entry["notify_sms"] is False


def test_run_burnin_check_breach_opens_incident(isolated_runtime, monkeypatch):
    _seed_burnin_started(days_ago=0)
    # Build ledger that breaches completed_merged_rate (0 merged out of 3)
    now = datetime.now(timezone.utc)
    for idx in range(3):
        _append_ledger_row(
            isolated_runtime,
            _make_complete_row(
                status="failed",
                completed_at=now - timedelta(hours=idx),
                run_id=f"fail-{idx}",
            ),
        )

    publish_calls: List[Dict[str, Any]] = []

    def fake_publish(*, event_type, payload, source, fingerprint=None):
        publish_calls.append(
            {
                "event_type": event_type,
                "payload": payload,
                "source": source,
                "fingerprint": fingerprint,
            }
        )
        return True

    # ``incident_bus.publish`` is imported lazily inside ``open_burnin_incident``.
    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        fake_publish,
    )

    result = run_burnin_check(now=now)

    assert result["ok"] is False  # breach → ok=False
    assert len(result["breaches"]) >= 1
    assert result["incidents_opened"] == len(result["breaches"])
    assert len(publish_calls) == len(result["breaches"])
    assert all(c["event_type"] == "ops.burnin.threshold_breached" for c in publish_calls)
    assert all(c["source"] == "self_maintenance_burnin" for c in publish_calls)
    assert all(c["fingerprint"] for c in publish_calls)


def test_run_burnin_check_expired_returns_expired(isolated_runtime):
    _seed_burnin_started(days_ago=TOTAL_BURNIN_DAYS)  # day 8

    result = run_burnin_check()

    assert result["ok"] is True
    assert result["active"] is False
    assert result["expired"] is True
    assert result["burnin_day"] == TOTAL_BURNIN_DAYS + 1


# --------------------------------------------------------------------------- #
# Extra: incident_bus fail-open path
# --------------------------------------------------------------------------- #


def test_open_burnin_incident_fail_open_when_bus_unavailable(isolated_runtime, monkeypatch):
    _seed_burnin_started(days_ago=0)

    breach = ThresholdBreach(
        metric="health",
        actual=0.3,
        threshold=0.5,
        direction="below_min",
        day_range="Day 1-2",
    )

    # Force incident_bus import to crash → fail-open
    def boom(*args, **kwargs):
        raise ImportError("simulated missing module")

    monkeypatch.setattr("builtins.__import__", boom)
    result = open_burnin_incident(breach, "Day 1-2", notify_sms=False)

    assert result is False


# --------------------------------------------------------------------------- #
# Extra: get_burnin_day_index boundary
# --------------------------------------------------------------------------- #


def test_get_burnin_day_index_zero_when_not_started(isolated_runtime):
    assert get_burnin_day_index() == 0


def test_get_burnin_day_index_increments_at_day_boundary(isolated_runtime):
    start = _seed_burnin_started(days_ago=2)  # day 3

    assert get_burnin_day_index(now=start + timedelta(days=2, hours=1)) == 3
    assert get_burnin_day_index(now=start + timedelta(days=3)) == 4


def test_set_burnin_start_at_returns_datetime(isolated_runtime):
    started_at = set_burnin_start_at(started_by="admin")

    assert isinstance(started_at, datetime)
    assert started_at.tzinfo is not None
    assert get_burnin_start_at() is not None
