"""file_retention_janitor 状态与空扫语义."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import modstore_server.models as models
from modstore_server.file_retention_janitor import (
    RetentionTarget,
    _is_actionable_warning,
    _process_target,
    prune_notifications,
    run_retention_janitor,
)


def test_is_actionable_warning() -> None:
    assert not _is_actionable_warning("目录不存在")
    assert _is_actionable_warning("glob 失败：permission denied")
    assert _is_actionable_warning("删除失败 foo：EBUSY")


def test_cli_emits_only_aggregate_retention_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import modstore_server.file_retention_janitor as janitor

    monkeypatch.setattr(
        janitor,
        "run_retention_janitor",
        lambda **_kwargs: {
            "status": "warning",
            "dry_run": True,
            "removed_count": 2,
            "released_bytes": 42,
            "warnings": ["private/customer/path"],
            "error": "",
            "report_md": "private/customer/path",
            "employee_id": "customer-employee-1",
        },
    )
    monkeypatch.setattr(sys, "argv", ["retention-janitor", "--json"])

    assert janitor._cli() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "status": "warning",
        "dry_run": True,
        "removed_count": 2,
        "released_bytes": 42,
        "warning_count": 1,
        "has_error": False,
    }


def test_missing_dir_is_note_not_metric_warning(tmp_path: Path) -> None:
    rep = _process_target(
        RetentionTarget(path="no_such_dir", ttl_days=1, description="test"),
        repo_root=tmp_path,
        dry_run=True,
        cumulative_released=0,
    )
    assert rep.exists is False
    assert any("目录不存在" in n for n in rep.notes)
    assert rep.warnings == []


def test_dry_run_all_missing_targets_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import modstore_server.file_retention_janitor as janitor

    monkeypatch.setattr(janitor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        janitor,
        "RETENTION_TARGETS",
        [
            RetentionTarget(path="a", ttl_days=1, description="a"),
            RetentionTarget(path="b", ttl_days=1, description="b"),
        ],
    )
    monkeypatch.setattr(janitor, "_resolve_admin_user_id", lambda: 0)
    monkeypatch.setattr(
        janitor,
        "prune_notifications",
        lambda **_kw: {"ok": True, "candidate_count": 0, "removed_count": 0},
    )

    out = run_retention_janitor(dry_run=True)
    assert out["status"] == "success"
    assert out["removed_count"] == 0
    assert out["released_bytes"] == 0
    assert out["warnings"] == []


def test_notification_retention_can_apply_while_file_targets_stay_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import modstore_server.file_retention_janitor as janitor

    calls: list[bool] = []
    monkeypatch.setattr(janitor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(janitor, "RETENTION_TARGETS", [])
    monkeypatch.setattr(janitor, "_resolve_admin_user_id", lambda: 0)

    def _prune(*, dry_run):
        calls.append(bool(dry_run))
        return {"ok": True, "candidate_count": 3, "removed_count": 3}

    monkeypatch.setattr(janitor, "prune_notifications", _prune)

    out = run_retention_janitor(dry_run=True, notification_dry_run=False)

    assert out["dry_run"] is True
    assert calls == [False]
    assert out["database_retention"]["removed_count"] == 3


def test_actionable_warning_raises_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import modstore_server.file_retention_janitor as janitor

    base = tmp_path / "webhook_events"
    base.mkdir()
    stale = base / "old.json"
    stale.write_text("{}", encoding="utf-8")
    old = 0.0
    stale.touch()
    import os
    import time

    old = time.time() - 40 * 86400
    os.utime(stale, (old, old))

    monkeypatch.setattr(janitor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        janitor,
        "RETENTION_TARGETS",
        [
            RetentionTarget(
                path="webhook_events",
                ttl_days=30,
                glob="*.json",
                recursive=False,
                description="test",
            ),
        ],
    )
    monkeypatch.setattr(janitor, "_resolve_admin_user_id", lambda: 0)
    monkeypatch.setattr(
        janitor,
        "prune_notifications",
        lambda **_kw: {"ok": True, "candidate_count": 0, "removed_count": 0},
    )

    def _fail_unlink(self, *a, **k):
        raise OSError("simulated delete failure")

    monkeypatch.setattr(Path, "unlink", _fail_unlink)

    out = run_retention_janitor(dry_run=False)
    assert out["status"] == "warning"
    assert out["warnings"]


def test_notification_retention_bounds_only_noisy_rows(tmp_path: Path, monkeypatch) -> None:
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "notification-retention.sqlite"))
    monkeypatch.setenv("MODSTORE_NOTIFICATION_SYSTEM_KEEP_PER_USER", "10")
    monkeypatch.setenv("MODSTORE_NOTIFICATION_EXECUTION_KEEP_PER_USER", "10")
    models.init_db()

    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    sf = models.get_session_factory()
    with sf() as session:
        users = [
            models.User(
                username=f"retention-admin-{index}",
                password_hash="x",
                email=f"retention-{index}@example.com",
                is_admin=True,
            )
            for index in range(2)
        ]
        session.add_all(users)
        session.flush()
        for user in users:
            session.add_all(
                [
                    models.Notification(
                        user_id=user.id,
                        kind="system",
                        title=f"system-{index}",
                        content="derived",
                        created_at=now - timedelta(minutes=index),
                    )
                    for index in range(15)
                ]
            )
            session.add_all(
                [
                    models.Notification(
                        user_id=user.id,
                        kind="employee_execution_done",
                        title=f"execution-{index}",
                        content="derived",
                        created_at=now - timedelta(minutes=index),
                    )
                    for index in range(13)
                ]
            )
            session.add(
                models.Notification(
                    user_id=user.id,
                    kind="payment_success",
                    title="payment",
                    content="business evidence",
                    created_at=now - timedelta(days=365),
                )
            )
        session.commit()

    preview = prune_notifications(dry_run=True, now=now)
    assert preview["candidate_count"] == 16
    assert preview["candidate_by_kind"] == {
        "employee_execution_done": 6,
        "system": 10,
    }
    assert preview["removed_count"] == 0

    applied = prune_notifications(dry_run=False, now=now)
    assert applied["candidate_count"] == 16
    assert applied["removed_count"] == 16
    assert applied["vacuum_recommended"] is True

    with sf() as session:
        for user in session.query(models.User).all():
            assert (
                session.query(models.Notification)
                .filter(
                    models.Notification.user_id == user.id,
                    models.Notification.kind == "system",
                )
                .count()
                == 10
            )
            assert (
                session.query(models.Notification)
                .filter(
                    models.Notification.user_id == user.id,
                    models.Notification.kind == "employee_execution_done",
                )
                .count()
                == 10
            )
            assert (
                session.query(models.Notification)
                .filter(
                    models.Notification.user_id == user.id,
                    models.Notification.kind == "payment_success",
                )
                .count()
                == 1
            )

    models._engine = None
    models._SessionFactory = None
