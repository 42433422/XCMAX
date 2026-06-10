"""容灾备份事件链 + DR 探针 + 按需快照 + 截图依赖探活。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate


def test_daily_backup_emits_completed_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modstore_server.daily_backup_job as bj

    ssot = tmp_path / "rt.json"
    ssot.write_text(json.dumps({"current": "1.0.0.0", "day_index": 0}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(
        bj, "_backup_sqlite", lambda *a, **k: {"ok": True, "path": "x", "bytes": 1, "pruned": 0}
    )
    monkeypatch.setattr(bj, "_backup_release_train", lambda *a, **k: {"ok": True, "skipped": True})

    emitted: list = []
    monkeypatch.setattr(
        "modstore_server.backup_event_subscriber.emit_backup_event",
        lambda et, payload: emitted.append((et, payload)) or {"dispatch": {"ok": True}},
    )

    out = bj.run_daily_backup_job()
    assert out["ok"] is True
    assert emitted and emitted[0][0] == "backup.completed"
    assert emitted[0][1].get("trigger") == "scheduled"


def test_dr_probe_recovers_and_clears_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modstore_server.daily_backup_job as bj
    import modstore_server.dr_recovery_probe_job as probe

    ssot = tmp_path / "rt.json"
    ssot.write_text(json.dumps({"current": "1.0.0.0", "day_index": 0}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_BACKUP_DIR", str(tmp_path / "backups"))

    from modstore_server.release_train import active_backup_guard, set_backup_guard

    set_backup_guard("disk full", day="2026-06-10")
    assert active_backup_guard(day="2026-06-10") is not None

    monkeypatch.setattr(
        bj, "_backup_sqlite", lambda *a, **k: {"ok": True, "path": "x", "bytes": 1, "pruned": 0}
    )
    monkeypatch.setattr(bj, "_backup_release_train", lambda *a, **k: {"ok": True, "skipped": True})

    events: list = []
    monkeypatch.setattr(
        "modstore_server.backup_event_subscriber.emit_backup_event",
        lambda et, payload: events.append(et) or {"dispatch": {"ok": True}},
    )

    out = probe.run_dr_recovery_probe()
    assert out.get("recovered") is True
    assert active_backup_guard(day="2026-06-10") is None
    assert "backup.dr_guard.cleared" in events


def test_dr_probe_escalates_after_max_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modstore_server.daily_backup_job as bj
    import modstore_server.dr_recovery_probe_job as probe

    ssot = tmp_path / "rt.json"
    ssot.write_text(json.dumps({"current": "1.0.0.0", "day_index": 0}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("MODSTORE_DR_PROBE_MAX_RETRIES", "2")

    from modstore_server.release_train import load_state, set_backup_guard

    guard = set_backup_guard("fail", day="2026-06-10")
    st = load_state(path=ssot)
    st["backup_guard"] = {**guard, "probe_retry_count": 1}
    ssot.write_text(json.dumps(st), encoding="utf-8")

    monkeypatch.setattr(bj, "_backup_sqlite", lambda *a, **k: {"ok": False, "error": "x"})
    monkeypatch.setattr(bj, "_backup_release_train", lambda *a, **k: {"ok": True, "skipped": True})

    events: list = []
    monkeypatch.setattr(
        "modstore_server.backup_event_subscriber.emit_backup_event",
        lambda et, payload: events.append(et) or {"dispatch": {"ok": True}},
    )
    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        lambda *a, **k: True,
    )

    out = probe.run_dr_recovery_probe()
    assert out.get("escalated") is True
    assert "backup.dr_guard.escalated" in events


def test_ondemand_backup_emits_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import modstore_server.daily_backup_job as bj
    import modstore_server.ondemand_backup as ob

    monkeypatch.setenv("MODSTORE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(
        bj, "_backup_sqlite", lambda *a, **k: {"ok": True, "path": "x", "bytes": 1, "pruned": 0}
    )
    monkeypatch.setattr(bj, "_backup_release_train", lambda *a, **k: {"ok": True, "skipped": True})

    events: list = []
    monkeypatch.setattr(
        "modstore_server.backup_event_subscriber.emit_backup_event",
        lambda et, payload: events.append(et) or {"dispatch": {"ok": True}},
    )

    out = ob.run_ondemand_backup(trigger="auto_rollback:FASTGATE", reason="smoke failed")
    assert out["ok"] is True
    assert "backup.ondemand_completed" in events
    assert "backup.completed" in events


def test_backup_completed_kicks_retention_janitor(monkeypatch: pytest.MonkeyPatch) -> None:
    from modstore_server.backup_event_subscriber import dispatch_backup_event

    kicked: list = []
    monkeypatch.setattr(
        "modstore_server.file_retention_janitor.run_retention_janitor",
        lambda: kicked.append(True) or {"ok": True, "status": "done"},
    )
    monkeypatch.setattr(
        "modstore_server.incident_bus.publish",
        lambda *a, **k: True,
    )

    out = dispatch_backup_event("backup.completed", {"trigger": "scheduled", "stamp": "t"})
    assert out["ok"] is True
    assert kicked


def test_surface_audit_deps_auto_start_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_AUTO_START", "0")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_PS_BASE_URL", "http://127.0.0.1:59999")

    from modstore_server.surface_audit_deps import ensure_surface_audit_deps

    out = ensure_surface_audit_deps()
    assert "services" in out
    assert out["services"].get("fhd_api", {}).get("reason") == "auto_start_disabled"
