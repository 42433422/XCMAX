from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import modstore_server.db.base as db_base
import modstore_server.models as models
from modstore_server.autonomy_decision_audit import (
    append_autonomy_decision,
    build_autonomy_decision_evidence,
)
from modstore_server.autonomy_posthoc_auditor import run_autonomy_posthoc_audit
from modstore_server.db.scheduler_ops import JobRun

UTC = timezone.utc
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "posthoc.sqlite"))
    models.init_db()
    yield models.get_session_factory()
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None


def _allow_metrics(sf) -> None:
    append_autonomy_decision(
        action_id="autonomy-metrics:2026-07-22",
        action="autonomy_metrics_snapshot",
        decision="allow",
        policy="autonomy_guard",
        risk_level="low",
        actor_class="system",
        source="autonomy_metrics.cron",
        occurred_at=NOW,
        session_factory=sf,
    )


def _write_metrics(path, *, complete: bool = True) -> None:
    windows = (30, 90) if complete else (30,)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "snapshot_date": "2026-07-22",
                    "snapshot_at": NOW.isoformat(),
                    "window_days": window,
                    "cohort": "operational",
                    "status": "collecting",
                    "has_prohibited_miss": False,
                }
            )
            + "\n"
            for window in windows
        ),
        encoding="utf-8",
    )


def test_correlates_allow_later_job_receipt_and_durable_artifact(
    session_factory,
    tmp_path,
):
    _allow_metrics(session_factory)
    artifact = tmp_path / "autonomy-metrics.jsonl"
    _write_metrics(artifact)
    with session_factory() as session:
        session.add(
            JobRun(
                job_id="autonomy_metrics_snapshot",
                status="success",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=2),
                duration_ms=2000,
                error="",
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        metrics_path=artifact,
        now=NOW + timedelta(seconds=3),
        session_factory=session_factory,
    )
    repeat = run_autonomy_posthoc_audit(
        metrics_path=artifact,
        now=NOW + timedelta(seconds=4),
        session_factory=session_factory,
    )
    evidence = build_autonomy_decision_evidence(
        now=NOW + timedelta(seconds=5),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 1
    assert result["append_only_evidence_written"] is True
    assert repeat["audited_count"] == 0
    assert evidence["has_prohibited_miss"] is False
    assert evidence["posthoc_coverage_rate"] == 100.0
    posthoc = next(item for item in evidence["items"] if item["record_type"] == "posthoc_anomaly")
    assert posthoc["source"] == "autonomy-posthoc-auditor.v1"
    assert posthoc["evidence_ref"].startswith("scheduler-job:")


def test_incomplete_artifact_remains_unknown(session_factory, tmp_path):
    _allow_metrics(session_factory)
    artifact = tmp_path / "autonomy-metrics.jsonl"
    _write_metrics(artifact, complete=False)
    with session_factory() as session:
        session.add(
            JobRun(
                job_id="autonomy_metrics_snapshot",
                status="success",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
                duration_ms=1000,
                error="",
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        metrics_path=artifact,
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )
    evidence = build_autonomy_decision_evidence(
        now=NOW + timedelta(seconds=3),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 0
    assert result["incomplete"] == [
        {
            "action_id": "autonomy-metrics:2026-07-22",
            "reason": "metrics_windows_incomplete",
        }
    ]
    assert evidence["has_prohibited_miss"] is None
    assert evidence["posthoc_coverage_rate"] == 0.0
