from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.desktop_runtime.backup_retention import cleanup_local_backups
from app.desktop_runtime.migrate import backup_database
from app.desktop_runtime.paths import ensure_desktop_dirs


def _backup(backups_dir: Path, name: str, age_days: int = 0) -> Path:
    path = backups_dir / name
    path.write_bytes(b"backup")
    timestamp = (datetime.now() - timedelta(days=age_days)).timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def _database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE proof (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO proof DEFAULT VALUES")


def test_cleanup_caps_automatic_backups_and_preserves_manual_files(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    oldest = _backup(backups, "xcagi-1.0.0-20260701000000.db", age_days=10)
    _backup(backups, "xcagi-1.0.0-20260702000000.db", age_days=3)
    weekly = _backup(backups, "xcagi-1.0.0-weekly-20260703000000.db", age_days=2)
    newest = _backup(backups, "xcagi-1.0.1-20260704000000.db", age_days=1)
    sidecar = oldest.with_name(f"{oldest.name}-wal")
    sidecar.write_bytes(b"wal")
    manual = _backup(backups, "xcagi-before-1.0.2-20260704-120000.db", age_days=20)
    user_backup = backups / "user-created.bak"
    user_backup.write_bytes(b"manual")

    removed = cleanup_local_backups(backups, keep=2)

    assert {path.name for path in removed} == {
        "xcagi-1.0.0-20260701000000.db",
        "xcagi-1.0.0-20260702000000.db",
    }
    assert newest.exists()
    assert weekly.exists()
    assert manual.exists()
    assert user_backup.exists()
    assert not sidecar.exists()


def test_cleanup_preserves_pending_rollback_backup_in_addition_to_limit(
    tmp_path: Path,
) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    rollback = _backup(backups, "xcagi-1.0.0-20260701000000.db", age_days=10)
    middle = _backup(backups, "xcagi-1.0.1-20260702000000.db", age_days=2)
    newest = _backup(backups, "xcagi-1.0.2-20260703000000.db", age_days=1)
    (tmp_path / "rollback-marker.json").write_text(
        json.dumps({"databaseBackupPath": str(rollback)}),
        encoding="utf-8",
    )

    cleanup_local_backups(backups, keep=1)

    assert rollback.exists()
    assert newest.exists()
    assert not middle.exists()


def test_backup_database_prunes_immediately_and_protects_new_backup(
    tmp_path: Path,
) -> None:
    dirs = ensure_desktop_dirs(tmp_path)
    _database(dirs["data"] / "xcagi.db")

    with patch("app.desktop_runtime.migrate.cleanup_local_backups") as cleanup:
        result = backup_database(tmp_path, version="1.0.0")

    assert result is not None
    assert result.exists()
    cleanup.assert_called_once_with(dirs["backups"], protected=(result,))
