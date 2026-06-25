"""Tests for daily scheduler coordination guards."""

from __future__ import annotations

import json
from datetime import datetime

from modstore_server.daily_backup_job import cron_trigger_for_backup
from modstore_server.daily_pipeline_lock import (
    scheduler_heartbeat_status,
    self_maintenance_loop_liveness,
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


_T0 = "2026-06-24T03:00:00+00:00"
_T0_EPOCH = datetime.fromisoformat(_T0).timestamp()


def test_loop_liveness_fresh_activity_not_stale() -> None:
    # 1 小时前刚跑过,远在 2 天阈值内
    out = self_maintenance_loop_liveness(_T0, now_epoch=_T0_EPOCH + 3600)
    assert out["is_stale"] is False
    assert out["reason"] == "ok"
    assert out["age_seconds"] == 3600


def test_loop_liveness_silent_past_threshold_is_stale() -> None:
    # 3 天没有任何 complete/skip → 停摆
    out = self_maintenance_loop_liveness(
        _T0, max_silence_seconds=172800, now_epoch=_T0_EPOCH + 3 * 86400
    )
    assert out["is_stale"] is True
    assert out["reason"] == "loop_stalled"


def test_loop_liveness_skip_counts_as_alive() -> None:
    # skip 也是"调度器有跳动",最近 skip 时间戳应让其判活
    out = self_maintenance_loop_liveness(_T0, now_epoch=_T0_EPOCH + 600)
    assert out["is_stale"] is False


def test_loop_liveness_no_activity_recorded_is_stale() -> None:
    out = self_maintenance_loop_liveness(None)
    assert out["is_stale"] is True
    assert out["reason"] == "no_activity_recorded"
    assert out["age_seconds"] is None


def test_loop_liveness_threshold_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_MAX_SILENCE_SEC", "60")
    out = self_maintenance_loop_liveness(_T0, now_epoch=_T0_EPOCH + 120)
    assert out["threshold_seconds"] == 60
    assert out["is_stale"] is True
