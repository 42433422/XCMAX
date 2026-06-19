"""Tests for daily scheduler coordination guards."""

from __future__ import annotations

import json

from modstore_server.daily_backup_job import cron_trigger_for_backup
from modstore_server.daily_pipeline_lock import (
    scheduler_heartbeat_status,
    write_scheduler_heartbeat,
)
from modstore_server.workflow_scheduler import (
    _business_misfire_grace_time,
    _cleanup_misfire_grace_time,
    _daily_pipeline_lock_wait_seconds,
)


def test_daily_backup_defaults_to_0400(monkeypatch) -> None:
    monkeypatch.delenv("MODSTORE_DAILY_BACKUP_HOUR", raising=False)
    monkeypatch.delenv("MODSTORE_DAILY_BACKUP_MINUTE", raising=False)

    trigger = str(cron_trigger_for_backup())

    assert "hour='4'" in trigger
    assert "minute='0'" in trigger


def test_scheduler_misfire_policy_defaults() -> None:
    assert _business_misfire_grace_time() == 3600
    assert _cleanup_misfire_grace_time() == 4 * 3600
    assert _daily_pipeline_lock_wait_seconds("daily_digest") == 0
    assert _daily_pipeline_lock_wait_seconds("daily_vibe_line_execute") == 90 * 60
    assert _daily_pipeline_lock_wait_seconds("release_train_orchestrator") == 90 * 60


def test_scheduler_heartbeat_writes_status(monkeypatch, tmp_path) -> None:
    heartbeat = tmp_path / "heartbeat.json"
    monkeypatch.setenv("MODSTORE_SCHEDULER_HEARTBEAT_FILE", str(heartbeat))

    written = write_scheduler_heartbeat(job_count=7)
    status = scheduler_heartbeat_status(max_age_seconds=60)
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))

    assert written["path"] == str(heartbeat)
    assert payload["job_count"] == 7
    assert status["ok"] is True
    assert status["heartbeat"]["job_count"] == 7
