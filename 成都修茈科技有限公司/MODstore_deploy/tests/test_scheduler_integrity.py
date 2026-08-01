from __future__ import annotations

import asyncio
from datetime import datetime, timezone


class _FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self.next_run_time = datetime.now(timezone.utc)
        self.trigger = "test"


class _FakeScheduler:
    running = True

    def __init__(self, job_ids: set[str]) -> None:
        self._jobs = [_FakeJob(job_id) for job_id in sorted(job_ids)]

    def get_jobs(self) -> list[_FakeJob]:
        return list(self._jobs)


def test_customer_value_startup_probe_failure_does_not_escape(monkeypatch):
    import modstore_server.workflow_scheduler as scheduler

    monkeypatch.setattr(scheduler, "_scheduler_startup_probe_failures", [])

    def unavailable() -> None:
        raise RuntimeError("customer_value_source_unready:java_postgresql_internal_api")

    assert scheduler._run_scheduler_startup_probe("customer_value_reconciler", unavailable) is False
    assert scheduler._scheduler_startup_probe_failures == [
        {
            "stage": "customer_value_reconciler",
            "error_type": "RuntimeError",
            "message": "customer_value_source_unready:java_postgresql_internal_api",
        }
    ]


def test_scheduler_integrity_rejects_partial_registration(monkeypatch):
    import modstore_server.workflow_scheduler as scheduler

    monkeypatch.setattr(
        scheduler,
        "_scheduler",
        _FakeScheduler(
            {
                "scheduler_heartbeat",
                "dead_letter_reconciler",
                "customer_value_reconciler",
            }
        ),
    )
    monkeypatch.setattr(scheduler, "_scheduler_registration_complete", False)
    monkeypatch.setattr(scheduler, "_scheduler_startup_probe_failures", [])

    status = scheduler.scheduler_integrity_status()

    assert status["engine_running"] is True
    assert status["registration_complete"] is False
    assert status["ok"] is False
    assert "employee_autonomy_dispatch_loop" in status["missing_required_jobs"]


def test_scheduler_integrity_accepts_complete_required_job_set(monkeypatch):
    import modstore_server.workflow_scheduler as scheduler

    required = set(scheduler.required_scheduler_job_ids())
    monkeypatch.setattr(scheduler, "_scheduler", _FakeScheduler(required))
    monkeypatch.setattr(scheduler, "_scheduler_registration_complete", True)
    monkeypatch.setattr(scheduler, "_scheduler_startup_probe_failures", [])

    status = scheduler.scheduler_integrity_status()

    assert status["ok"] is True
    assert status["active_job_count"] == status["required_job_count"]
    assert status["missing_required_jobs"] == []
    assert "storage_pressure_self_heal" in required
    assert "capability_proposal_relay" in required


def test_scheduler_health_endpoint_exposes_partial_registration(monkeypatch):
    import modstore_server.workflow_scheduler as scheduler
    from modstore_server.api.health import _scheduler_status
    from modstore_server.xcmax_admin_api import scheduler_health

    monkeypatch.setattr(
        scheduler,
        "_scheduler",
        _FakeScheduler(
            {
                "scheduler_heartbeat",
                "dead_letter_reconciler",
                "customer_value_reconciler",
            }
        ),
    )
    monkeypatch.setattr(scheduler, "_scheduler_registration_complete", False)
    monkeypatch.setattr(scheduler, "_scheduler_startup_probe_failures", [])
    monkeypatch.setattr(
        scheduler,
        "scheduler_runtime_health_status",
        lambda: {"ok": True, "jobs": [], "unhealthy_jobs": [], "recovering_jobs": []},
    )

    response = asyncio.run(scheduler_health())

    assert response["success"] is True
    assert response["ok"] is False
    assert response["data"]["scheduler_running"] is True
    assert response["data"]["scheduler_healthy"] is False
    assert response["data"]["registration_complete"] is False
    assert response["data"]["missing_required_jobs"]
    assert _scheduler_status() is False


def test_scheduler_health_endpoint_accepts_complete_registration(monkeypatch):
    import modstore_server.workflow_scheduler as scheduler
    from modstore_server.xcmax_admin_api import scheduler_health

    required = set(scheduler.required_scheduler_job_ids())
    monkeypatch.setattr(scheduler, "_scheduler", _FakeScheduler(required))
    monkeypatch.setattr(scheduler, "_scheduler_registration_complete", True)
    monkeypatch.setattr(scheduler, "_scheduler_startup_probe_failures", [])
    monkeypatch.setattr(
        scheduler,
        "scheduler_runtime_health_status",
        lambda: {"ok": True, "jobs": [], "unhealthy_jobs": [], "recovering_jobs": []},
    )

    response = asyncio.run(scheduler_health())

    assert response["success"] is True
    assert response["ok"] is True
    assert response["data"]["scheduler_running"] is True
    assert response["data"]["scheduler_healthy"] is True
    assert response["data"]["registration_complete"] is True
    assert response["data"]["missing_required_jobs"] == []


def test_stale_daily_job_gets_bounded_startup_catch_up(monkeypatch):
    import modstore_server.scheduler_runtime as runtime
    import modstore_server.workflow_scheduler as scheduler

    monkeypatch.setattr(scheduler, "_scheduler_startup_recovery_deadlines", {})
    monkeypatch.setattr(
        runtime,
        "get_runtime_status",
        lambda **_kwargs: {
            "ok": True,
            "jobs": [{"job_id": "daily_digest", "state": "stale"}],
        },
    )

    kwargs = scheduler._startup_recovery_kwargs("daily_digest", delay_seconds=5)

    assert kwargs["next_run_time"] > datetime.now(timezone.utc)
    assert "daily_digest" in scheduler._scheduler_startup_recovery_deadlines


def test_healthy_daily_job_keeps_normal_cron_schedule(monkeypatch):
    import modstore_server.scheduler_runtime as runtime
    import modstore_server.workflow_scheduler as scheduler

    monkeypatch.setattr(
        runtime,
        "get_runtime_status",
        lambda **_kwargs: {
            "ok": True,
            "jobs": [{"job_id": "daily_digest", "state": "healthy"}],
        },
    )

    assert scheduler._startup_recovery_kwargs("daily_digest", delay_seconds=5) == {}
