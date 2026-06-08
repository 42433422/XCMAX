"""DRFAIL 灾备守卫 + 门禁失败自动回滚闭环（对齐时间轨 DRFAIL / ROLLBACK 节点）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate


def test_backup_guard_skips_bump_until_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modstore_server.release_train import (
        active_backup_guard,
        bump_release_train,
        clear_backup_guard,
        load_state,
        set_backup_guard,
    )

    ssot = tmp_path / "rt.json"
    ssot.write_text(
        json.dumps({"epoch": "1.0.0.0", "current": "1.0.0.0", "day_index": 0}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_ENABLED", "1")
    monkeypatch.delenv("MODSTORE_RELEASE_TRAIN_FORCE_BUMP", raising=False)

    set_backup_guard("daily backup failed: boom", day="2026-06-07")
    assert active_backup_guard(day="2026-06-07") is not None
    # 守卫按日历日匹配，跨日不再生效
    assert active_backup_guard(day="2026-06-08") is None

    out = bump_release_train(digest_day="2026-06-07")
    assert out["skipped"] is True
    assert out["reason"] == "backup_failed_guard"
    assert out["after"] == "1.0.0.0"
    assert load_state(path=ssot)["current"] == "1.0.0.0"  # 未递增

    # force 可绕过守卫
    forced = bump_release_train(digest_day="2026-06-07", force=True)
    assert forced["skipped"] is False
    assert forced["after"] == "1.0.0.1"

    # 人工/次日成功备份解除守卫后恢复递增
    clear_backup_guard()
    assert active_backup_guard(day="2026-06-07") is None
    out2 = bump_release_train(digest_day="2026-06-08")
    assert out2["skipped"] is False
    assert out2["after"] == "1.0.0.2"


def test_daily_backup_failure_sets_guard_and_alerts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modstore_server.daily_backup_job as bj
    import modstore_server.incident_bus as ib

    ssot = tmp_path / "rt.json"
    ssot.write_text(json.dumps({"current": "1.0.0.5", "day_index": 5}), encoding="utf-8")
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(ssot))
    monkeypatch.setenv("MODSTORE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(bj, "_backup_sqlite", lambda *a, **k: {"ok": False, "error": "disk full"})
    monkeypatch.setattr(bj, "_backup_release_train", lambda *a, **k: {"ok": True, "skipped": True})

    alerts: list = []
    monkeypatch.setattr(ib, "publish", lambda *a, **k: alerts.append((a, k)) or True)

    out = bj.run_daily_backup_job()
    assert out["ok"] is False
    assert out["degrade"]["alerted"] is True
    assert out["degrade"]["guard"]["day"]
    assert alerts and alerts[0][0][0] == "log.anomaly"

    from modstore_server.release_train import active_backup_guard

    assert active_backup_guard() is not None

    # 恢复：成功备份解除守卫
    monkeypatch.setattr(
        bj, "_backup_sqlite", lambda *a, **k: {"ok": True, "path": "x", "bytes": 1, "pruned": 0}
    )
    out2 = bj.run_daily_backup_job()
    assert out2["ok"] is True
    assert active_backup_guard() is None


def test_auto_rollback_closure_rolls_back_and_stages_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import modstore_server.incident_bus as ib
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "ar.sqlite"))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_JSON", str(tmp_path / "rt.json"))
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_AUTO_ROLLBACK_ENABLED", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    models.init_db()

    monkeypatch.setattr(ib, "publish", lambda *a, **k: True)

    from modstore_server.release_train import bump_release_train

    bump_release_train(digest_day="2026-06-01")  # 1.0.0.0 -> 1.0.0.1
    bump_release_train(digest_day="2026-06-02")  # -> 1.0.0.2

    from modstore_server.auto_rollback import auto_rollback_on_gate_failure

    out = auto_rollback_on_gate_failure(
        gate="FASTGATE",
        release_train="1.0.0.2",
        release_kind="installer",
        reason="staging/health smoke failed",
    )
    assert out["ok"] is True
    assert out["rollback"]["ok"] is True
    assert out["rollback"]["after"] == "1.0.0.1"
    assert out["alert"]["published"] is True
    assert out["staged_change"]["ok"] is True

    from modstore_server.models import OpsStagedChange, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = session.get(OpsStagedChange, int(out["staged_change"]["staged_id"]))
    assert row is not None
    assert row.status == "pending"
    assert row.created_by_employee_id == "deploy-release-officer"
    assert "auto-rollback" in row.branch

    models._engine = None
    models._SessionFactory = None


def test_auto_rollback_disabled_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_AUTO_ROLLBACK_ENABLED", "0")
    from modstore_server.auto_rollback import auto_rollback_on_gate_failure

    out = auto_rollback_on_gate_failure(gate="CANARY", release_kind="installer", reason="x")
    assert out["ok"] is True
    assert out["skipped"] is True
    assert "rollback" not in out
