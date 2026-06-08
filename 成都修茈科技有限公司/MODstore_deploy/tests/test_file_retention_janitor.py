"""file_retention_janitor 状态与空扫语义."""

from __future__ import annotations

from pathlib import Path

import pytest

from modstore_server.file_retention_janitor import (
    RetentionTarget,
    _is_actionable_warning,
    _process_target,
    run_retention_janitor,
)


def test_is_actionable_warning() -> None:
    assert not _is_actionable_warning("目录不存在")
    assert _is_actionable_warning("glob 失败：permission denied")
    assert _is_actionable_warning("删除失败 foo：EBUSY")


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

    out = run_retention_janitor(dry_run=True)
    assert out["status"] == "success"
    assert out["removed_count"] == 0
    assert out["released_bytes"] == 0
    assert out["warnings"] == []


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

    def _fail_unlink(self, *a, **k):
        raise OSError("simulated delete failure")

    monkeypatch.setattr(Path, "unlink", _fail_unlink)

    out = run_retention_janitor(dry_run=False)
    assert out["status"] == "warning"
    assert out["warnings"]
