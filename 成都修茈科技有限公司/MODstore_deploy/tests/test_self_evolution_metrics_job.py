from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modstore_server.self_evolution_knowledge import evolution_metrics_gate
from modstore_server.self_evolution_metrics_job import (
    SCHEMA,
    _junit_counts,
    _qa_child_env,
    run_self_evolution_metrics_snapshot,
)


def _coverage(_root: Path, _now: datetime) -> dict:
    return {
        "backend_coverage": 88.4,
        "covered_lines": 100,
        "num_statements": 120,
        "observed_at": "2026-07-22T00:00:00+00:00",
        "age_hours": 1.0,
        "artifact_sha256": "a" * 64,
        "source": "coverage.json",
    }


def _debt(_root: Path) -> dict:
    return {
        "type_debt": 12,
        "counts": {"type_ignore": 2, "ts_nocheck": 0, "frontend_any": 10},
        "duration_ms": 5,
        "script_sha256": "b" * 64,
        "output_sha256": "c" * 64,
    }


def _qa(_root: Path) -> dict:
    return {
        "pytest_passed": 16,
        "tests": 18,
        "skipped": 2,
        "failures": 0,
        "errors": 0,
        "duration_ms": 50,
        "junit_sha256": "d" * 64,
        "targets": ["tests/test_runtime_provenance.py"],
        "python": "/runtime/python",
    }


def test_verified_weekly_snapshot_records_once(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    monkeypatch.setattr(
        "modstore_server.self_evolution_metrics_job.collect_runtime_provenance",
        lambda: {
            "ok": False,
            "source": "immutable_manifest",
            "manifest_sha": "e" * 40,
            "head_sha": "e" * 40,
        },
    )
    now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)

    first = run_self_evolution_metrics_snapshot(
        root=tmp_path,
        now=now,
        _coverage_collector=_coverage,
        _type_debt_collector=_debt,
        _qa_collector=_qa,
    )
    second = run_self_evolution_metrics_snapshot(
        root=tmp_path,
        now=now,
        _coverage_collector=_coverage,
        _type_debt_collector=_debt,
        _qa_collector=_qa,
    )

    assert first["evidence_verified"] is True
    assert first["runtime_provenance_ok"] is False
    assert second == {
        "ok": True,
        "reason": "verified_week_already_recorded",
        "schema": SCHEMA,
        "skipped": True,
        "week": "2026-W30",
    }
    gate = evolution_metrics_gate()
    assert gate["history_count"] == 1
    assert gate["verified_history_count"] == 1
    assert gate["raw_history_count"] == 1


def test_metrics_gate_does_not_count_unverified_legacy_record(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    metrics = tmp_path / "kb" / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "evolution_metrics.jsonl").write_text(
        '{"week":"2026-W29","backend_coverage":80,"pytest_passed":2,'
        '"type_debt":10,"metadata":{}}\n',
        encoding="utf-8",
    )

    gate = evolution_metrics_gate()

    assert gate["history_count"] == 0
    assert gate["raw_history_count"] == 1
    assert gate["reason"] == "insufficient_metrics_history"


def test_junit_counts_exclude_skipped_and_failures(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites tests="20" failures="1" errors="1" skipped="2"></testsuites>',
        encoding="utf-8",
    )

    assert _junit_counts(junit) == {
        "tests": 20,
        "failures": 1,
        "errors": 1,
        "skipped": 2,
        "passed": 16,
    }


def test_snapshot_fails_closed_when_coverage_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))

    def missing(_root: Path, _now: datetime) -> dict:
        raise RuntimeError("coverage_artifact_unavailable")

    with pytest.raises(RuntimeError, match="coverage_artifact_unavailable"):
        run_self_evolution_metrics_snapshot(
            root=tmp_path,
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            _coverage_collector=missing,
            _type_debt_collector=_debt,
            _qa_collector=_qa,
        )


def test_fresh_coverage_from_fixed_qa_suite_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("XCMAX_SELF_EVOLUTION_KB_ROOT", str(tmp_path / "kb"))
    monkeypatch.setattr(
        "modstore_server.self_evolution_metrics_job.collect_runtime_provenance",
        lambda: {"ok": True, "source": "immutable_manifest"},
    )

    def qa_with_coverage(_root: Path) -> dict:
        return {
            **_qa(_root),
            "coverage": {
                "backend_coverage": 42.5,
                "covered_lines": 42,
                "num_statements": 100,
                "observed_at": "2026-07-22T12:00:00+00:00",
                "age_hours": 0.0,
                "artifact_sha256": "f" * 64,
                "source": "fixed_autonomy_qa_suite",
                "scope": "modstore_server",
            },
        }

    def stale_should_not_run(_root: Path, _now: datetime) -> dict:
        raise AssertionError("stale external coverage must not be consulted")

    result = run_self_evolution_metrics_snapshot(
        root=tmp_path,
        now=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        _coverage_collector=stale_should_not_run,
        _type_debt_collector=_debt,
        _qa_collector=qa_with_coverage,
    )

    assert result["backend_coverage"] == 42.5


def test_fixed_qa_environment_excludes_runtime_secrets_and_release_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "sensitive-value")
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", "/runtime/manifest.json")
    monkeypatch.setenv("MODSTORE_DB_PATH", "/runtime/live.db")
    monkeypatch.setenv("MODSTORE_DAILY_ENV_CLEANROOM", "1")

    child = _qa_child_env(tmp_path / "project", tmp_path / "temp")

    assert "MINIMAX_API_KEY" not in child
    assert "MODSTORE_RELEASE_MANIFEST" not in child
    assert "MODSTORE_DB_PATH" not in child
    assert "MODSTORE_DAILY_ENV_CLEANROOM" not in child
    assert child["PYTHONNOUSERSITE"] == "1"


def test_fixed_qa_environment_uses_repository_shared_package(tmp_path):
    repo_root = tmp_path / "repo"
    project = repo_root / "成都修茈科技有限公司" / "MODstore_deploy"
    shared_package = repo_root / "packages" / "xcagi_common"
    shared_package.mkdir(parents=True)

    child = _qa_child_env(project, tmp_path / "temp")

    assert str(shared_package) in child["PYTHONPATH"].split(os.pathsep)
