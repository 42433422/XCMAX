"""Runtime-truth ledger: record job runs, surface stalled jobs, expose via API."""

from __future__ import annotations

import json
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


def test_track_job_run_records_expected_policy_hold_as_deferred(db_ready):
    from modstore_server.scheduler_runtime import (
        DeferredJobRun,
        get_runtime_status,
        track_job_run,
    )

    job_id = _job("policy_hold")
    with track_job_run(job_id):
        raise DeferredJobRun("retort_clarification_pending")

    entry = _find(get_runtime_status(), job_id)
    assert entry is not None
    assert entry["state"] == "deferred"
    assert entry["last_status"] == "deferred"
    assert entry["consecutive_failures"] == 0


def test_employee_cron_failure_code_is_safe_for_public_runtime(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status, record_job_run

    job_id = f"employee_cron:{uuid.uuid4().hex[:12]}"
    record_job_run(
        job_id=job_id,
        status="failed",
        started_at=datetime.now(timezone.utc),
        error=(
            "RuntimeError('employee_cron_unsuccessful:handler_failed:quota "
            "provider_response=api_key=must-not-leak')"
        ),
    )

    entry = _find(get_runtime_status(), job_id)
    assert entry is not None
    assert entry["last_error_code"] == "employee_cron_unsuccessful:handler_failed:quota"
    assert "must-not-leak" not in json.dumps(entry, ensure_ascii=False)


def test_deferred_employee_cron_is_not_reported_as_failure(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status, record_job_run

    job_id = f"employee_cron_registered:{uuid.uuid4().hex[:12]}"
    record_job_run(
        job_id=job_id,
        status="deferred",
        started_at=datetime.now(timezone.utc),
        error="employee_cron_policy_deferred:approval_required_high_risk",
    )

    status = get_runtime_status()
    entry = _find(status, job_id)
    assert entry is not None
    assert entry["state"] == "deferred"
    assert entry["consecutive_failures"] == 0
    assert entry["last_error_code"] == "employee_cron_policy_deferred:approval_required_high_risk"
    assert status["summary"]["deferred"] >= 1


def test_workflow_scheduler_non_daily_job_uses_runtime_ledger(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status
    from modstore_server.workflow_scheduler import _run_tracked_scheduler_job

    job_id = _job("employee_loop")
    result = _run_tracked_scheduler_job(job_id, lambda: {"ok": True})

    entry = _find(get_runtime_status(), job_id)
    assert result == {"ok": True}
    assert entry is not None
    assert entry["state"] == "healthy"
    assert entry["last_status"] == "success"


def test_customer_value_scheduler_requires_authoritative_source():
    from modstore_server.workflow_scheduler import _require_customer_value_source_ready

    ready = {"source_ready": True, "source_owner": "java_postgresql_internal_api"}
    assert _require_customer_value_source_ready(ready) is ready

    with pytest.raises(
        RuntimeError,
        match="customer_value_source_unready:java_postgresql_internal_api",
    ):
        _require_customer_value_source_ready(
            {
                "source_ready": False,
                "source_owner": "java_postgresql_internal_api",
            }
        )


def test_customer_value_unready_source_is_recorded_as_job_failure(db_ready):
    from modstore_server.scheduler_runtime import get_runtime_status
    from modstore_server.workflow_scheduler import _run_authoritative_customer_value_job

    with pytest.raises(
        RuntimeError,
        match="customer_value_source_unready:java_postgresql_internal_api",
    ):
        _run_authoritative_customer_value_job(
            lambda: {
                "source_ready": False,
                "source_owner": "java_postgresql_internal_api",
            }
        )

    entry = _find(get_runtime_status(), "customer_value_reconciler")
    assert entry is not None
    assert entry["state"] == "failing"
    assert entry["last_status"] == "failed"
    assert entry["consecutive_failures"] >= 1


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
    duty = body["employee_duty"]
    assert set(duty) == {
        "registration_observable",
        "registered_cron_count",
        "registration_failing_count",
        "approval_required_count",
        "observed_cron_count",
        "last_success_count",
        "failing_count",
        "failure_code_counts",
        "never_run_count",
        "approval_required_observed_execution_count",
        "unregistered_observed_count",
    }
    assert isinstance(duty["registration_observable"], bool)
    assert isinstance(duty["failure_code_counts"], dict)
    assert all(
        isinstance(duty[name], int)
        for name in set(duty) - {"registration_observable", "failure_code_counts"}
    )


def test_runtime_status_aggregates_registered_employee_duty(monkeypatch):
    import modstore_server.api.scheduler_runtime_api as runtime_api

    monkeypatch.setattr(
        "modstore_server.storage_pressure_self_heal.get_storage_pressure_status",
        lambda **_kwargs: {"ok": True, "latest": {"status": "healthy_no_action"}},
    )

    monkeypatch.setattr(
        runtime_api,
        "get_runtime_status",
        lambda **_kwargs: {
            "ok": True,
            "jobs": [
                {
                    "job_id": "employee_cron_registered:one",
                    "last_status": "success",
                },
                {
                    "job_id": "employee_cron_registered:two",
                    "last_status": "success",
                },
                {
                    "job_id": "employee_cron_registered:never-ran",
                    "last_status": "success",
                },
                {
                    "job_id": "employee_cron_registered:registration-failed",
                    "last_status": "failed",
                },
                {
                    "job_id": "employee_cron_registered:approval-required",
                    "last_status": "deferred",
                },
                {"job_id": "employee_cron:one", "last_status": "success"},
                {
                    "job_id": "employee_cron:two",
                    "last_status": "failed",
                    "last_error_code": "employee_cron_unsuccessful:handler_failed:quota",
                },
                {"job_id": "employee_cron:approval-required", "last_status": "failed"},
                {"job_id": "employee_cron:old-unregistered", "last_status": "success"},
            ],
            "summary": {"total": 3, "healthy": 2, "failing": 1, "stale": 0},
        },
    )

    body = runtime_api.scheduler_runtime()

    assert body["employee_duty"] == {
        "registration_observable": True,
        "registered_cron_count": 3,
        "registration_failing_count": 1,
        "approval_required_count": 1,
        "observed_cron_count": 2,
        "last_success_count": 1,
        "failing_count": 1,
        "failure_code_counts": {"employee_cron_unsuccessful:handler_failed:quota": 1},
        "never_run_count": 1,
        "approval_required_observed_execution_count": 1,
        "unregistered_observed_count": 1,
    }
    assert body["storage_pressure"]["latest"]["status"] == "healthy_no_action"
