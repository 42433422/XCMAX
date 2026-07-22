from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modstore_server.self_maintenance_loop_runner import (
    _select_recent_milestone_rows,
)


NOW = datetime(2026, 7, 22, 14, 0, tzinfo=timezone.utc)


def _row(
    *,
    run_id: str,
    phase: str,
    minutes_ago: int,
    step: str = "",
    status: str = "",
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "phase": phase,
        "step": step,
        "status": status,
        "timestamp": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
    }


def test_heartbeats_cannot_evict_recent_coherent_work_evidence() -> None:
    rows = [
        _row(run_id="incident-1", phase="start", minutes_ago=50, status="running"),
        _row(
            run_id="incident-1",
            phase="step",
            step="code",
            minutes_ago=40,
            status="success",
        ),
        _row(
            run_id="incident-1",
            phase="step",
            step="review",
            minutes_ago=30,
            status="success",
        ),
        _row(
            run_id="incident-1",
            phase="step",
            step="qa",
            minutes_ago=20,
            status="success",
        ),
        _row(
            run_id="incident-1",
            phase="complete",
            minutes_ago=10,
            status="completed_merged",
        ),
    ]
    rows.extend(
        _row(
            run_id=f"heartbeat-{index}",
            phase="heartbeat",
            minutes_ago=9 - min(index, 9),
            status="heartbeat_idle",
        )
        for index in range(400)
    )

    selected = _select_recent_milestone_rows(rows, now=NOW)

    assert [row["phase"] for row in selected] == [
        "start",
        "step",
        "step",
        "step",
        "complete",
    ]
    assert {row["run_id"] for row in selected} == {"incident-1"}


def test_milestone_evidence_expires_and_rejects_timeless_rows() -> None:
    selected = _select_recent_milestone_rows(
        [
            {
                "run_id": "timeless",
                "phase": "step",
                "step": "code",
                "status": "success",
            },
            {
                **_row(
                    run_id="stale",
                    phase="step",
                    step="qa",
                    minutes_ago=0,
                    status="success",
                ),
                "timestamp": (NOW - timedelta(days=31)).isoformat(),
            },
            _row(
                run_id="fresh",
                phase="step",
                step="qa",
                minutes_ago=5,
                status="success",
            ),
        ],
        now=NOW,
        window_days=30,
    )

    assert [row["run_id"] for row in selected] == ["fresh"]
