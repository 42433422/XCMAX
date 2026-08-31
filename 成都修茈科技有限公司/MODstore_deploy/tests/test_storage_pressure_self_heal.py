"""Fault-injection coverage for the storage-pressure autonomous repair loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import modstore_server.storage_pressure_self_heal as self_heal

GIB = 1024**3


def _usage(*, free_gib: int, used_gib: int, total_gib: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        total=total_gib * GIB,
        used=used_gib * GIB,
        free=free_gib * GIB,
    )


def _sequence(*values: SimpleNamespace):
    rows = iter(values)

    def _disk_usage(_path: str) -> SimpleNamespace:
        return next(rows)

    return _disk_usage


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODSTORE_STORAGE_MONITOR_PATH", str(tmp_path))
    monkeypatch.setenv("MODSTORE_STORAGE_MIN_FREE_GIB", "10")
    monkeypatch.setenv("MODSTORE_STORAGE_MAX_USED_PERCENT", "90")
    monkeypatch.setenv("MODSTORE_STORAGE_RECOVERY_MIN_FREE_GIB", "12")
    monkeypatch.setenv("MODSTORE_STORAGE_RECOVERY_MAX_USED_PERCENT", "88")
    monkeypatch.setenv("MODSTORE_STORAGE_SELF_HEAL_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_STORAGE_SELF_HEAL_COOLDOWN_MINUTES", "60")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(self_heal, "_database_size_bytes", lambda: 0)
    monkeypatch.setattr(self_heal, "_record_alignment_decision", lambda **_kwargs: None)


def _retention_result(*, files: int, notifications: int, released_bytes: int = 0) -> dict:
    return {
        "ok": True,
        "status": "success",
        "removed_count": files,
        "released_bytes": released_bytes,
        "database_retention": {
            "removed_count": notifications,
            "truncated": False,
        },
    }


def test_healthy_storage_is_observed_without_cleanup() -> None:
    calls: list[dict] = []

    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(_usage(free_gib=70, used_gib=30)),
        retention_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert result["ok"] is True
    assert result["status"] == "healthy_no_action"
    assert result["action_taken"] is False
    assert calls == []
    assert self_heal.get_storage_pressure_status()["latest"]["status"] == "healthy_no_action"


def test_audit_ledger_rotates_instead_of_growing_without_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = self_heal.audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"status":"older"}\n', encoding="utf-8")
    monkeypatch.setattr(self_heal, "_audit_max_bytes", lambda: 1)

    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(_usage(free_gib=70, used_gib=30)),
    )

    assert result["status"] == "healthy_no_action"
    assert self_heal._audit_archive_path().read_text(encoding="utf-8") == ('{"status":"older"}\n')
    assert self_heal.get_storage_pressure_status()["latest"]["run_id"] == result["run_id"]


def test_pressure_executes_bounded_retention_and_requires_hysteresis_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action_calls: list[dict] = []
    decisions: list[dict] = []
    monkeypatch.setattr(
        self_heal,
        "_record_alignment_decision",
        lambda **kwargs: decisions.append(kwargs),
    )

    def _retention(**kwargs):
        action_calls.append(kwargs)
        return _retention_result(files=2, notifications=4, released_bytes=14 * GIB)

    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(
            _usage(free_gib=5, used_gib=95),
            _usage(free_gib=20, used_gib=80),
        ),
        retention_runner=_retention,
        notification_verifier=lambda **_kwargs: {"candidate_count": 0},
    )

    assert result["ok"] is True
    assert result["status"] == "recovered"
    assert result["action_taken"] is True
    assert action_calls == [{"dry_run": False, "notification_dry_run": False}]
    assert decisions[0]["decision"] == "allow"
    assert result["postcondition"] == {
        "pressure_detected": True,
        "recovery_verified": True,
        "physical_reclaim_observed": True,
        "free_bytes_delta": 15 * GIB,
        "logical_retention_verified": True,
        "business_notification_scope_unchanged_by_contract": True,
    }


def test_logical_delete_without_physical_recovery_is_not_reported_as_repaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incidents: list[dict] = []
    monkeypatch.setattr(
        self_heal,
        "_publish_unresolved_incident",
        lambda result: incidents.append(result) is None,
    )

    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(
            _usage(free_gib=5, used_gib=95),
            _usage(free_gib=5, used_gib=95),
        ),
        retention_runner=lambda **_kwargs: _retention_result(files=0, notifications=10),
        notification_verifier=lambda **_kwargs: {"candidate_count": 0},
    )

    assert result["ok"] is False
    assert result["status"] == "pressure_persists"
    assert result["postcondition"]["physical_reclaim_observed"] is False
    assert result["postcondition"]["logical_retention_verified"] is True
    assert len(incidents) == 1


def test_pressure_with_no_allowlisted_candidates_escalates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_heal, "_publish_unresolved_incident", lambda _result: True)
    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(
            _usage(free_gib=5, used_gib=95),
            _usage(free_gib=5, used_gib=95),
        ),
        retention_runner=lambda **_kwargs: _retention_result(files=0, notifications=0),
        notification_verifier=lambda **_kwargs: {"candidate_count": 0},
    )

    assert result["ok"] is False
    assert result["status"] == "no_safe_candidates"
    assert result["incident_emitted"] is True


def test_retention_failure_is_a_failed_repair_and_escalates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incidents: list[dict] = []
    monkeypatch.setattr(
        self_heal,
        "_publish_unresolved_incident",
        lambda result: incidents.append(result) is None,
    )

    def _raise(**_kwargs):
        raise OSError("simulated retention failure")

    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(
            _usage(free_gib=5, used_gib=95),
            _usage(free_gib=5, used_gib=95),
        ),
        retention_runner=_raise,
        notification_verifier=lambda **_kwargs: {"candidate_count": 0},
    )

    assert result["ok"] is False
    assert result["status"] == "repair_failed"
    assert result["incident_emitted"] is True
    assert len(incidents) == 1


def test_recent_action_enforces_cooldown_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_heal, "_publish_unresolved_incident", lambda _result: True)
    now = datetime.now(timezone.utc)
    first = self_heal.run_storage_pressure_self_heal(
        now=now,
        disk_usage_fn=_sequence(
            _usage(free_gib=5, used_gib=95),
            _usage(free_gib=5, used_gib=95),
        ),
        retention_runner=lambda **_kwargs: _retention_result(files=0, notifications=1),
        notification_verifier=lambda **_kwargs: {"candidate_count": 0},
    )
    assert first["action_taken"] is True

    calls: list[dict] = []
    second = self_heal.run_storage_pressure_self_heal(
        now=now + timedelta(minutes=1),
        disk_usage_fn=_sequence(_usage(free_gib=5, used_gib=95)),
        retention_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert second["status"] == "pressure_cooldown"
    assert second["ok"] is False
    assert second["action_taken"] is False
    assert calls == []


def test_operator_veto_blocks_cleanup_and_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODSTORE_STORAGE_SELF_HEAL_ENABLED", "0")
    decisions: list[dict] = []
    monkeypatch.setattr(
        self_heal,
        "_record_alignment_decision",
        lambda **kwargs: decisions.append(kwargs),
    )
    calls: list[dict] = []

    result = self_heal.run_storage_pressure_self_heal(
        disk_usage_fn=_sequence(_usage(free_gib=5, used_gib=95)),
        retention_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert result["ok"] is False
    assert result["status"] == "operator_veto"
    assert result["action_taken"] is False
    assert calls == []
    assert decisions[0]["decision"] == "block"
    assert decisions[0]["policy"] == "storage_self_heal_disabled_by_operator_veto"


def test_unresolved_result_fails_scheduler_contract() -> None:
    with pytest.raises(RuntimeError, match="storage_self_heal_unresolved:pressure_persists"):
        self_heal.require_successful_storage_self_heal({"ok": False, "status": "pressure_persists"})


def test_unresolved_incident_uses_daily_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def _capture(event_type, payload, **kwargs):
        calls.append({"event_type": event_type, "payload": payload, **kwargs})
        return True

    monkeypatch.setattr("modstore_server.incident_bus.publish", _capture)
    assert self_heal._publish_unresolved_incident({"status": "repair_failed", "after": {}})
    assert calls[0]["dedupe_minutes"] == 24 * 60


def test_scheduler_registration_tracks_startup_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[dict] = []
    tracked: list[str] = []
    probed: list[str] = []

    class _Scheduler:
        def add_job(self, fn, trigger, **kwargs):
            registered.append({"fn": fn, "trigger": trigger, **kwargs})

    monkeypatch.setattr(
        self_heal,
        "run_storage_pressure_self_heal",
        lambda: {"ok": True, "status": "healthy_no_action", "action_taken": False},
    )

    def _track(job_id, fn):
        tracked.append(job_id)
        return fn()

    def _probe(name, fn):
        probed.append(name)
        fn()
        return True

    self_heal.register_storage_pressure_job(
        _Scheduler(),
        track_job=_track,
        startup_probe=_probe,
        misfire_grace_time=3600,
    )

    assert registered[0]["id"] == "storage_pressure_self_heal"
    assert registered[0]["max_instances"] == 1
    assert tracked == ["storage_pressure_self_heal"]
    assert probed == ["storage_pressure_self_heal"]
