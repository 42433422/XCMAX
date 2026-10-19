"""Unit tests for admin autonomy overview helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.application.autonomy.admin_overview import (
    closure_gap_count,
    evaluate_cross_tier_gate_snapshot,
    extract_loop_run_summary,
    list_deploy_events,
    operating_metrics_windows,
    read_cross_tier_audit,
)


def test_list_deploy_events_reads_jsonl(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "deploy_events.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "deploy_id": "d1",
                        "deployed_at": "2026-07-01T00:00:00Z",
                        "status": "success",
                        "head_branch": "main",
                        "source_workflow": "Deploy",
                        "commit_at": "2026-07-01T00:00:00Z",
                        "restored_at": None,
                    }
                ),
                json.dumps(
                    {
                        "deploy_id": "d2",
                        "deployed_at": "2026-07-02T00:00:00Z",
                        "status": "failed",
                        "head_branch": "main",
                        "source_workflow": "CI",
                        "commit_at": "2026-07-02T00:00:00Z",
                        "restored_at": None,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
    data = list_deploy_events(limit=10)
    assert data["count"] == 2
    assert data["items"][0]["deploy_id"] == "d2"


def test_extract_loop_and_gap_helpers() -> None:
    summary = extract_loop_run_summary(
        {
            "memory": {
                "last_run": {
                    "run_id": "r1",
                    "status": "completed_held_for_remediation",
                    "branch": "devfleet/x",
                }
            }
        }
    )
    assert summary["run_id"] == "r1"
    assert summary["status"] == "completed_held_for_remediation"
    assert closure_gap_count({"data": {"gaps": [1, 2, 3]}}) == 3


def test_cross_tier_gate_snapshot_runs() -> None:
    snap = evaluate_cross_tier_gate_snapshot(
        {
            "server_manifest_frozen": False,
            "desktop_pending_rollback_marker": False,
        }
    )
    assert snap["ok"] is True
    assert len(snap["rules"]) == 3


def test_operating_metrics_windows_shape() -> None:
    data = operating_metrics_windows()
    assert "30" in data["windows"]
    assert "90" in data["windows"]
    assert "veto_rate" in data["windows"]["30"]


def test_cross_audit_distinguishes_missing_empty_bad_and_stale(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(path))
    monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "unused"))
    assert read_cross_tier_audit(tier="server")["status"] == "not_connected"
    path.write_text("")
    assert read_cross_tier_audit(tier="server")["status"] == "empty"
    path.write_text("{broken json}")
    assert read_cross_tier_audit(tier="server")["status"] == "error"
    path.write_bytes(b"\xff")
    assert read_cross_tier_audit(tier="server")["status"] == "error"
    for age, status in ((0, "ready"), (48, "stale"), (-48, "unknown_freshness")):
        stamp = (datetime.now(UTC) - timedelta(hours=age)).isoformat()
        path.write_text(json.dumps({"timestamp": stamp, "action": {"type": "clear_logs"}}))
        result = read_cross_tier_audit(tier="server")
        assert result["status"] == status
        assert result["last_event_at"] == stamp
        assert result["count"] == 1


def test_cross_audit_reports_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    path.write_text("{}")
    monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(path))
    def denied(*args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "read_text", denied)
    assert read_cross_tier_audit(tier="server")["status"] == "error"
