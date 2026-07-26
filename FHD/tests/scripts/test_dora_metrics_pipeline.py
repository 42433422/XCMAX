from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.dev import gen_claimed_vs_actual
from scripts.observability.collect_dora import compute_dora

FHD_ROOT = Path(__file__).resolve().parents[2]


def _event(
    deployed_at: str,
    *,
    status: str = "success",
    environment: str = "production",
    commit_at: str | None = None,
) -> dict:
    return {
        "deploy_id": deployed_at,
        "deployed_at": deployed_at,
        "commit_at": commit_at or deployed_at,
        "status": status,
        "restored_at": None,
        "source_workflow": "test",
        "head_branch": "main",
        "environment": environment,
        "git_sha": "a" * 40,
    }


def test_compute_dora_filters_to_production_window() -> None:
    now = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    events = [
        _event(
            "2026-07-25T12:00:00Z",
            commit_at="2026-07-25T10:00:00Z",
        ),
        _event("2026-07-24T12:00:00Z", status="failed"),
        _event("2026-07-25T12:00:00Z", environment="staging"),
        _event("2026-07-01T12:00:00Z"),
    ]

    report = compute_dora(
        events,
        window_days=7,
        environment="production",
        now=now,
    )

    assert report["environment"] == "production"
    assert report["source_event_count"] == 3
    assert report["event_count"] == 2
    assert report["successes"] == 1
    assert report["failures"] == 1
    assert report["deployment_frequency_per_day"] == 0.1429
    assert report["lead_time_for_changes_hours"] == 2.0
    assert report["change_failure_rate"] == 0.5


def test_dora_event_helper_persists_machine_readable_receipt(tmp_path: Path) -> None:
    event_log = tmp_path / "dora-deploy-events.jsonl"
    helper = FHD_ROOT / "scripts" / "deploy" / "lib" / "dora_event.sh"
    env = {
        **os.environ,
        "FHD_DORA_EVENT_LOG": str(event_log),
    }

    subprocess.run(
        [
            "bash",
            "-c",
            (
                f"source {helper!s}; "
                "dora_emit_deployment success "
                f"{'b' * 40} 2026-07-26T08:00:00Z production image 10.0.0 test"
            ),
        ],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    event = json.loads(event_log.read_text(encoding="utf-8"))
    assert event["status"] == "success"
    assert event["environment"] == "production"
    assert event["git_sha"] == "b" * 40
    assert event["commit_at"] == "2026-07-26T08:00:00Z"
    assert event["deploy_mode"] == "image"
    assert event["source_workflow"] == "test"
    assert event_log.stat().st_mode & 0o777 == 0o600


def test_latest_dora_snapshot_uses_newest_dated_file(tmp_path: Path) -> None:
    older = tmp_path / "dora-20260720.json"
    latest = tmp_path / "dora-20260726.json"
    ignored = tmp_path / "dora-monthly-202607.json"
    older.write_text('{"event_count": 1}\n', encoding="utf-8")
    latest.write_text('{"event_count": 4}\n', encoding="utf-8")
    ignored.write_text('{"event_count": 99}\n', encoding="utf-8")

    report, path = gen_claimed_vs_actual._latest_dora_snapshot(tmp_path)

    assert report["event_count"] == 4
    assert path == latest


def test_dora_snapshot_age_exposes_stale_data() -> None:
    age = gen_claimed_vs_actual._snapshot_age_days(
        "2026-07-20T08:00:00Z",
        now=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
    )

    assert age == 6


def test_release_package_and_auto_update_wire_dora_receipts() -> None:
    pack = (FHD_ROOT / "scripts" / "deploy" / "fhd-pack-release.sh").read_text()
    auto_update = (FHD_ROOT / "scripts" / "deploy" / "fhd-auto-update.sh").read_text()

    assert '"$SCRIPT_DIR/lib/dora_event.sh"' in pack
    assert 'record_dora_deployment "success"' in auto_update
    assert 'record_dora_deployment "failed"' in auto_update
