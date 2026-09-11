"""桌面启动兜底迁移（ensure_startup_migration）单元测试。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.desktop_runtime import migrate


def _make_stamped_db(database: Path, revision: str) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(database))
    try:
        conn.execute("create table alembic_version (version_num varchar(32) not null)")
        conn.execute("insert into alembic_version values (?)", (revision,))
        conn.commit()
    finally:
        conn.close()


def _patch_migrate_env(monkeypatch: pytest.MonkeyPatch, database: Path) -> None:
    # migrate.py 以 ``from .paths import`` 绑定，须 patch migrate 命名空间内的绑定
    monkeypatch.setattr(migrate, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(migrate, "ensure_desktop_dirs", lambda _path: {"data": database.parent})
    monkeypatch.setattr(migrate, "backup_database", Mock(return_value=None))
    monkeypatch.setattr(migrate, "run_alembic_upgrade", Mock(return_value=None))


def test_ensure_startup_migration_skips_when_schema_at_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "data" / "xcagi.db"
    _make_stamped_db(database, "2026_07_05_employee_run_logs")
    _patch_migrate_env(monkeypatch, database)
    monkeypatch.setattr(
        migrate, "_known_alembic_revisions", lambda: {"2026_07_05_employee_run_logs"}
    )
    monkeypatch.setattr(migrate, "_current_head_revision", lambda: "2026_07_05_employee_run_logs")

    result = migrate.ensure_startup_migration(str(tmp_path))

    assert result == {"action": "skipped", "detail": "schema already at head"}
    migrate.backup_database.assert_not_called()  # type: ignore[attr-defined]
    migrate.run_alembic_upgrade.assert_not_called()  # type: ignore[attr-defined]


def test_ensure_startup_migration_backs_up_then_upgrades_when_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "data" / "xcagi.db"
    _make_stamped_db(database, "2026_07_05_employee_run_logs")
    _patch_migrate_env(monkeypatch, database)
    known = {"2026_07_05_employee_run_logs", "2026_08_20_repair_products_uom"}
    monkeypatch.setattr(migrate, "_known_alembic_revisions", lambda: known)
    monkeypatch.setattr(migrate, "_current_head_revision", lambda: "2026_08_20_repair_products_uom")
    migrate.backup_database.return_value = tmp_path / "backups" / "xcagi-test.db"

    result = migrate.ensure_startup_migration(str(tmp_path))

    assert result == {"action": "upgraded", "detail": "schema migrated at startup"}
    migrate.backup_database.assert_called_once()  # type: ignore[attr-defined]
    migrate.run_alembic_upgrade.assert_called_once_with(str(tmp_path))  # type: ignore[attr-defined]


def test_ensure_startup_migration_refuses_without_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "data" / "xcagi.db"
    _make_stamped_db(database, "2026_07_05_employee_run_logs")
    _patch_migrate_env(monkeypatch, database)
    monkeypatch.setattr(
        migrate,
        "backup_database",
        Mock(return_value=None),  # 备份失败
    )
    monkeypatch.setattr(
        migrate, "_known_alembic_revisions", lambda: {"2026_07_05_employee_run_logs"}
    )
    monkeypatch.setattr(migrate, "_current_head_revision", lambda: "2026_08_20_head")

    with pytest.raises(RuntimeError, match="migration backup failed"):
        migrate.ensure_startup_migration(str(tmp_path))
    migrate.run_alembic_upgrade.assert_not_called()  # type: ignore[attr-defined]


def test_ensure_startup_migration_fresh_data_dir_bootstraps_without_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "data" / "xcagi.db"  # 首启：库不存在
    _patch_migrate_env(monkeypatch, database)

    result = migrate.ensure_startup_migration(str(tmp_path))

    assert result == {"action": "upgraded", "detail": "schema migrated at startup"}
    migrate.backup_database.assert_not_called()  # type: ignore[attr-defined]
    migrate.run_alembic_upgrade.assert_called_once_with(str(tmp_path))  # type: ignore[attr-defined]


def test_is_schema_current_reports_pending_and_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "data" / "xcagi.db"
    _make_stamped_db(database, "2026_07_05_employee_run_logs")
    _patch_migrate_env(monkeypatch, database)
    known = {"2026_07_05_employee_run_logs", "2026_08_20_repair_products_uom"}
    monkeypatch.setattr(migrate, "_known_alembic_revisions", lambda: known)
    monkeypatch.setattr(migrate, "_current_head_revision", lambda: "2026_08_20_repair_products_uom")

    assert migrate.is_schema_current(str(tmp_path)) is False
    assert migrate.is_schema_current(str(tmp_path / "missing-root")) is False


def test_ensure_startup_migration_skips_when_peer_migrated_under_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """并发启动：拿到锁后若对端已完成迁移，则跳过备份与升级。"""
    database = tmp_path / "data" / "xcagi.db"
    _make_stamped_db(database, "2026_07_05_employee_run_logs")
    _patch_migrate_env(monkeypatch, database)
    calls = {"n": 0}

    def _is_current(_path: object) -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # 锁外 False，持锁后复查 True

    monkeypatch.setattr(migrate, "is_schema_current", _is_current)

    result = migrate.ensure_startup_migration(str(tmp_path))

    assert result == {"action": "skipped", "detail": "schema already at head"}
    migrate.backup_database.assert_not_called()  # type: ignore[attr-defined]
    migrate.run_alembic_upgrade.assert_not_called()  # type: ignore[attr-defined]


def test_ensure_startup_migration_serializes_on_data_dir_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """迁移必须持有 data 目录下的跨进程互斥锁（阻塞 + 拒绝符号链接）。"""
    database = tmp_path / "data" / "xcagi.db"
    _make_stamped_db(database, "2026_07_05_employee_run_logs")
    _patch_migrate_env(monkeypatch, database)
    known = {"2026_07_05_employee_run_logs", "2026_08_20_repair_products_uom"}
    monkeypatch.setattr(migrate, "_known_alembic_revisions", lambda: known)
    monkeypatch.setattr(migrate, "_current_head_revision", lambda: "2026_08_20_repair_products_uom")
    migrate.backup_database.return_value = tmp_path / "backups" / "xcagi-test.db"

    seen: dict[str, object] = {}
    real_lock = migrate.exclusive_file_lock

    @contextmanager
    def _spy(path: object, **kwargs: object):
        seen["path"] = Path(str(path))
        seen["kwargs"] = kwargs
        with real_lock(path, **kwargs):  # type: ignore[arg-type]
            yield

    monkeypatch.setattr(migrate, "exclusive_file_lock", _spy)

    migrate.ensure_startup_migration(str(tmp_path))

    assert seen["path"] == database.parent / migrate._MIGRATION_LOCK_NAME
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["blocking"] is True
    assert kwargs["reject_symlink"] is True
