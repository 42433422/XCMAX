"""Runtime-truth ledger: record job runs, surface stalled jobs, expose via API."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def db_ready():
    import modstore_server.models  # noqa: F401  (registers JobRun on Base.metadata)
    from modstore_server.db.base import init_db

    init_db()
    yield


def _job(prefix: str) -> str:
    return f"pytest_{prefix}_{uuid.uuid4().hex[:12]}"


def _find(status: dict, job_id: str) -> dict | None:
    return next((j for j in status["jobs"] if j["job_id"] == job_id), None)


def test_record_and_read_roundtrip(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status, record_job_run

    job_id = _job("roundtrip")
    now = datetime.now(timezone.utc)
    record_job_run(
        job_id=job_id,
        status="success",
        started_at=now,
        finished_at=now,
        duration_ms=12.5,
    )

    entry = _find(get_runtime_status(), job_id)
    assert entry is not None
    assert entry["state"] == "healthy"
    assert entry["last_status"] == "success"
    assert entry["last_success_at"] is not None
    assert entry["runs_counted"] == 1


def test_track_job_run_failure_reraises_and_records(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status, track_job_run

    job_id = _job("boom")
    with pytest.raises(ValueError, match="kaboom"):
        with track_job_run(job_id):
            raise ValueError("kaboom")

    entry = _find(get_runtime_status(), job_id)
    assert entry is not None
    assert entry["state"] == "failing"
    assert entry["last_status"] == "failed"
    assert entry["consecutive_failures"] == 1
    # never succeeded → no last_success
    assert entry["last_success_at"] is None


def test_stale_when_last_success_too_old(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status, record_job_run

    job_id = _job("frozen")
    old = datetime.now(timezone.utc) - timedelta(days=2)
    record_job_run(job_id=job_id, status="success", started_at=old, finished_at=old)

    # The job DID run successfully — just not recently. Heartbeat-style liveness would
    # miss this; the ledger flags it as stale.
    entry = _find(get_runtime_status(stale_after_seconds=3600), job_id)
    assert entry is not None
    assert entry["state"] == "stale"
    assert entry["last_status"] == "success"
    assert entry["seconds_since_success"] > 3600


def test_recovery_clears_consecutive_failures(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status, record_job_run

    job_id = _job("recover")
    base = datetime.now(timezone.utc)
    record_job_run(job_id=job_id, status="failed", started_at=base, error="x")
    record_job_run(job_id=job_id, status="success", started_at=base + timedelta(seconds=1))

    entry = _find(get_runtime_status(), job_id)
    assert entry is not None
    assert entry["state"] == "healthy"
    assert entry["consecutive_failures"] == 0
    assert entry["runs_counted"] == 2


def test_skip_is_not_a_failure(db_ready):
    from modstore_server.scheduler_runtime import (
        get_runtime_status,
        record_job_run,
        record_skip,
    )

    job_id = _job("skip")
    now = datetime.now(timezone.utc)
    record_job_run(job_id=job_id, status="success", started_at=now, finished_at=now)
    record_skip(job_id, reason="daily_pipeline_lock_busy")

    entry = _find(get_runtime_status(), job_id)
    assert entry is not None
    # A skip after a healthy success must not flip the job to failing.
    assert entry["state"] == "healthy"
    assert entry["last_status"] == "skipped"
    assert entry["consecutive_failures"] == 0


def test_runtime_status_endpoint(client):
    resp = client.get("/api/scheduler/runtime")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["jobs"], list)
    assert {"total", "healthy", "failing", "stale"} <= set(body["summary"])
    assert "stale_after_seconds" in body
