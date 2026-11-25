from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.dev import gen_claimed_vs_actual, product_lines_status
from scripts.observability.collect_dora import compute_dora

FHD_ROOT = Path(__file__).resolve().parents[2]


def _event(
    deployed_at: str,
    *,
    status: str = "success",
    environment: str = "production",
    commit_at: str | None = None,
    restored_at: str | None = None,
) -> dict:
    return {
        "deploy_id": deployed_at,
        "deployed_at": deployed_at,
        "commit_at": commit_at or deployed_at,
        "status": status,
        "restored_at": restored_at,
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


@pytest.mark.parametrize(
    ("restored_at", "expected_hours", "sample_count"),
    [
        (None, None, 0),
        ("2026-07-25T12:00:00Z", 0.0, 1),
        ("2026-07-25T13:30:00Z", 1.5, 1),
        ("2026-07-25T11:59:00Z", None, 0),
        ("2026-07-27T12:00:00Z", None, 0),
    ],
)
def test_mttr_requires_an_observed_restoration_receipt(
    restored_at: str | None, expected_hours: float | None, sample_count: int
) -> None:
    events = [
        _event("2026-07-25T12:00:00Z", status="failed", restored_at=restored_at),
        # A later successful retry is not evidence of this incident's recovery time.
        _event("2026-07-25T18:00:00Z"),
        _event("2026-07-25T10:00:00Z", environment="staging", restored_at="2026-07-25T11:00:00Z"),
        _event("2026-07-01T10:00:00Z", restored_at="2026-07-01T11:00:00Z"),
    ]
    report = compute_dora(
        events, environment="production", now=datetime(2026, 7, 26, 12, tzinfo=UTC)
    )
    assert report["mean_time_to_restore_hours"] == expected_hours
    assert report["mean_time_to_restore_sample_count"] == sample_count


def test_mttr_averages_only_valid_explicit_restorations() -> None:
    events = [
        _event("2026-07-25T10:00:00Z", restored_at="2026-07-25T11:00:00Z"),
        _event("2026-07-25T12:00:00Z", restored_at="2026-07-25T15:00:00Z"),
        _event("2026-07-25T18:00:00Z", status="failed"),
    ]
    report = compute_dora(events, now=datetime(2026, 7, 26, 12, tzinfo=UTC))
    assert report["mean_time_to_restore_hours"] == 2.0
    assert report["mean_time_to_restore_sample_count"] == 2


@pytest.mark.parametrize(
    ("hours", "samples", "expected", "count_label", "status"),
    [
        (None, 0, "未知", "0", gen_claimed_vs_actual.ST_YELLOW),
        (0.0, None, "未知", "未知", gen_claimed_vs_actual.ST_YELLOW),
        (0.0, 0, "未知", "0", gen_claimed_vs_actual.ST_YELLOW),
        (0.0, 1, "0 小时", "1", gen_claimed_vs_actual.ST_GREEN),
        (2.0, 2, "2 小时", "2", gen_claimed_vs_actual.ST_GREEN),
    ],
)
def test_claimed_actual_distinguishes_unknown_mttr_from_measured_zero(
    tmp_path: Path, monkeypatch, hours, samples, expected, count_label, status
) -> None:
    snapshot = {"event_count": 4, "mean_time_to_restore_hours": hours}
    if samples is not None:
        snapshot["mean_time_to_restore_sample_count"] = samples
    (tmp_path / "dora-20260726.json").write_text(json.dumps(snapshot), encoding="utf-8")
    load_snapshot = gen_claimed_vs_actual._latest_dora_snapshot
    monkeypatch.setattr(
        gen_claimed_vs_actual, "_latest_dora_snapshot", lambda: load_snapshot(tmp_path)
    )

    rows, _ = gen_claimed_vs_actual.build_rows()
    row = next(row for row in rows if row[0] == "DORA 平均恢复时长")
    assert row[2] == f"{expected} / 有效恢复样本 {count_label}"
    assert row[3] == "dora-20260726.json"
    assert row[4] == status


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


def test_dora_snapshot_line_reports_absolute_collection_date() -> None:
    # 曾经输出「N 天内采集」相对量：无任何输入变更也会天天失效（漂移门禁误报）
    assert gen_claimed_vs_actual._snapshot_date("2026-07-20T08:00:00Z") == "2026-07-20"
    assert gen_claimed_vs_actual._snapshot_date("") == "未知"
    assert not hasattr(gen_claimed_vs_actual, "_snapshot_age_days")


def test_release_package_and_auto_update_wire_dora_receipts() -> None:
    pack = (FHD_ROOT / "scripts" / "deploy" / "fhd-pack-release.sh").read_text()
    auto_update = (FHD_ROOT / "scripts" / "deploy" / "fhd-auto-update.sh").read_text()

    assert '"$SCRIPT_DIR/lib/dora_event.sh"' in pack
    assert 'record_dora_deployment "success"' in auto_update
    assert 'record_dora_deployment "failed"' in auto_update


@pytest.mark.parametrize(
    "identity",
    [{}, {"commit": "a" * 40, "captured_at": "2026-07-25T11:34:00Z"}],
)
def test_regeneration_does_not_promote_old_coverage_to_current_pass(
    tmp_path, monkeypatch, identity
):
    snapshot = {
        "committed_head": {**identity, "frontend_line_pct": 100.0},
        "targets": {"frontend_line_pct": 80},
        "quality_gate": {"status": "passed"},
    }
    path = tmp_path / "coverage-dual-summary.json"
    path.write_text(json.dumps(snapshot))
    monkeypatch.setattr(gen_claimed_vs_actual, "METRICS_DIR", tmp_path)
    rows, _ = gen_claimed_vs_actual.build_rows()
    measured = next(row for row in rows if row[0] == "前端行覆盖率（历史样本）")
    provenance = next(row for row in rows if row[0] == "覆盖率证据范围")
    assert measured[2] == "100.0%" and measured[4] == gen_claimed_vs_actual.ST_YELLOW
    assert identity.get("commit", "未知") in provenance[2]
    assert identity.get("captured_at", "未知") in provenance[2]
    assert "本版未验证" in provenance[2]
    assert json.loads(path.read_text()) == snapshot


@pytest.mark.parametrize("llm_verified", [False, True])
def test_model_mode_marker_never_substitutes_for_current_task_receipts(
    tmp_path, monkeypatch, llm_verified
):
    marker = {
        "mode": "monitoring",
        "status": "UNVERIFIED",
        "llm_verified": llm_verified,
        "sha": "b" * 40,
        "observed_at": "2026-11-16T18:41:16+08:00",
        "reason": "规则引擎口径，不构成 LLM 实测验收",
    }
    (tmp_path / "benchmark_run_mode.json").write_text(json.dumps(marker))
    monkeypatch.setattr(gen_claimed_vs_actual, "METRICS_DIR", tmp_path)
    rows, _ = gen_claimed_vs_actual.build_rows()
    row = next(row for row in rows if row[0] == "真实模型任务验收")
    assert row[4] == gen_claimed_vs_actual.ST_YELLOW
    for value in ("本版未验证", marker["sha"], marker["observed_at"], marker["reason"]):
        assert value in row[2]


def test_product_view_separates_recorded_gate_from_current_verification(monkeypatch):
    source = product_lines_status.load_config()["sources"]["coverage"]
    load_json = product_lines_status._load_json
    snapshot = {
        "committed_head": {"commit": "c" * 40, "captured_at": "2026-07-25T11:34:00Z"},
        "quality_gate": {"status": "passed", "reason": "historical evidence"},
    }
    monkeypatch.setattr(
        product_lines_status,
        "_load_json",
        lambda path: snapshot if path == source else load_json(path),
    )
    # Isolate the coverage-projection test from unrelated acceptance history.
    # A shallow Actions checkout cannot resolve every historical evidence commit.
    builder = product_lines_status._capability_builder()
    # Keep the complete capability-summary contract while isolating unrelated evidence Git history.
    empty_stats = {
        "total": 0,
        "modules": 0,
        "domains": 0,
        "by_status": dict.fromkeys(("verified", "partial", "implemented", "planned"), 0),
        "platform_counts": {},
    }
    monkeypatch.setattr(builder, "build", lambda: ({"stats": empty_stats}, [], []))
    monkeypatch.setattr(product_lines_status, "_capability_builder", lambda: builder)
    status = product_lines_status.build_status()
    coverage = status["coverage"]
    assert coverage["recorded_quality_gate"] == snapshot["quality_gate"]
    assert "quality_gate" not in coverage
    assert coverage["provenance"]["current_source_status"] == "UNVERIFIED"
    rendered = product_lines_status.render_doc(status)
    assert "原记录门禁：passed" in rendered and "本版验证：UNVERIFIED" in rendered
    assert "c" * 40 in rendered and "2026-07-25T11:34:00Z" in rendered


def test_benchmark_marker_refresh_requires_regenerated_claimed_vs_actual(tmp_path, monkeypatch):
    """Marker refresh must invalidate and then regenerate the derived SSOT."""
    marker_path = tmp_path / "benchmark_run_mode.json"
    output = tmp_path / "CLAIMED_VS_ACTUAL.md"
    monkeypatch.setattr(gen_claimed_vs_actual, "METRICS_DIR", tmp_path)
    monkeypatch.setattr(gen_claimed_vs_actual, "OUTPUT_DOC", output)
    marker = {
        "mode": "monitoring",
        "status": "UNVERIFIED",
        "llm_verified": False,
        "sha": "a" * 40,
        "observed_at": "2026-11-22T12:00:00+08:00",
    }
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["gen_claimed_vs_actual.py"])
    assert gen_claimed_vs_actual.main() == 0
    monkeypatch.setattr("sys.argv", ["gen_claimed_vs_actual.py", "--check"])
    assert gen_claimed_vs_actual.main() == 0
    marker.update(
        mode="acceptance",
        status="VERIFIED",
        llm_verified=True,
        sha="b" * 40,
        observed_at="2026-11-23T12:00:00+08:00",
    )
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    assert gen_claimed_vs_actual.main() == 1  # stale doc must fail
    monkeypatch.setattr("sys.argv", ["gen_claimed_vs_actual.py"])
    assert gen_claimed_vs_actual.main() == 0
    monkeypatch.setattr("sys.argv", ["gen_claimed_vs_actual.py", "--check"])
    assert gen_claimed_vs_actual.main() == 0
    doc = output.read_text(encoding="utf-8")
    assert "b" * 40 in doc and marker["observed_at"] in doc
    assert "本版未验证" in doc  # the mode marker is not acceptance evidence


def test_benchmark_workflows_commit_regenerated_claimed_vs_actual():
    """Both source and root mirrors must commit the derived doc with metrics."""
    paths = (
        FHD_ROOT / ".github/workflows/intent-benchmark.yml",
        FHD_ROOT.parent / ".github/workflows/fhd-intent-benchmark.yml",
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert content.count("python scripts/dev/gen_claimed_vs_actual.py\n") == 2
        assert content.count("python scripts/dev/gen_claimed_vs_actual.py --check\n") == 2
        assert content.count("git add metrics/ docs/CLAIMED_VS_ACTUAL.md") == 2
