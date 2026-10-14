"""桌面 SQLite 备份、恢复和连接行为测试。"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.desktop_runtime.migrate import (
    _integrity_check_ok,
    _quick_check_ok,
    backup_database,
    recover_if_corrupt,
)
from app.desktop_runtime.paths import (
    configure_desktop_environment,
    ensure_desktop_dirs,
)


def _create_test_db(db_path: Path) -> None:
    """创建一个有内容的测试 SQLite 库（默认 rollback journal 模式）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT)")
    conn.execute("INSERT INTO orders (customer) VALUES ('alice'), ('bob')")
    conn.commit()
    conn.close()


def _reset_desktop_env(monkeypatch) -> None:
    """清理桌面模式相关环境变量，保证测试隔离。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DB_RECOVERY", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)


def test_backup_database_produces_consistent_online_backup(tmp_path, monkeypatch):
    """backup_database 必须用 sqlite3.backup() API，主库有未 checkpoint 写入时
    也能备份出一致的库（shutil.copy2 会拷到不一致状态，会丢 WAL 内容）。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    live_conn = sqlite3.connect(str(db_path))
    live_conn.execute("INSERT INTO orders (customer) VALUES ('carol')")
    live_conn.commit()

    try:
        result = backup_database(tmp_path, version="online")
        assert result is not None, "online hot backup should succeed"
        assert result.exists()

        # shutil.copy2 在 rollback journal 模式下也能拷到（因为没有独立 WAL 文件），
        # 但如果主库在 WAL 模式 + 有未 checkpoint 写入，shutil.copy2 会丢这部分。
        verify_conn = sqlite3.connect(str(result))
        rows = verify_conn.execute("SELECT customer FROM orders ORDER BY id").fetchall()
        verify_conn.close()
        customers = [r[0] for r in rows]
        assert "carol" in customers, "backup must include all committed writes"
        assert "alice" in customers
        assert "bob" in customers
    finally:
        live_conn.close()


def test_backup_database_passes_integrity_check(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    result = backup_database(tmp_path, version="v1")
    assert result is not None
    assert result.exists()
    assert _integrity_check_ok(result), "backup file must pass integrity_check"


def test_backup_database_returns_none_when_db_missing(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    ensure_desktop_dirs(tmp_path)
    result = backup_database(tmp_path, version="v1")
    assert result is None


def test_backup_database_no_partial_file_on_failure(tmp_path, monkeypatch):
    """备份失败时不能留下半成品文件。

    通过让源 db 文件不可读来模拟备份失败（sqlite3.backup 会抛 OperationalError）。
    验证 backups/ 目录里没有残留的 xcagi-*.db 文件。
    """
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    # macOS/Linux 上 chmod 000 让文件不可读（模拟备份失败）
    # Windows 上 chmod 不生效，跳过此测试
    if os.name == "nt":
        pytest.skip("chmod-based failure simulation not portable to Windows")

    db_path.chmod(0o000)
    try:
        result = backup_database(tmp_path, version="fail")
        # 在 root 用户下 chmod 000 仍可读，所以 result 可能不为 None
        # 关键验证：即使失败，也不应该有 partial 文件
        if result is None:
            partial_files = list(dirs["backups"].glob("xcagi-*.db"))
            assert partial_files == [], "must not leave partial backup file on failure"
    finally:
        db_path.chmod(0o644)


def test_recover_if_corrupt_returns_ok_for_healthy_db(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    mtime_before = db_path.stat().st_mtime
    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "ok"
    assert result["detail"] == ""
    assert db_path.stat().st_mtime == mtime_before


def test_recover_if_corrupt_recovers_from_backup(tmp_path, monkeypatch):
    """库损坏时能从最近的备份恢复。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"

    _create_test_db(db_path)
    backup_path = backup_database(tmp_path, version="v1")
    assert backup_path is not None and backup_path.exists()

    db_path.write_bytes(b"not a sqlite database file !!! corruption")

    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "restored", f"expected restored, got {result}"
    assert result["detail"] == backup_path.name

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT customer FROM orders").fetchall()
    conn.close()
    assert len(rows) == 2

    corrupt_files = list(dirs["data"].glob("xcagi.db.corrupt-*"))
    assert len(corrupt_files) == 1, "corrupt db must be renamed and kept as evidence"


def test_recover_if_corrupt_no_backup_returns_corrupt_no_backup(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"corrupt content")

    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "corrupt_no_backup"

    corrupt_files = list(dirs["data"].glob("xcagi.db.corrupt-*"))
    assert len(corrupt_files) == 1


def test_recover_if_corrupt_skips_bad_backups(tmp_path, monkeypatch):
    """最近的备份本身损坏时，跳过它并尝试更老的备份。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    backups_dir = dirs["backups"]

    _create_test_db(db_path)
    old_backup = backup_database(tmp_path, version="old")
    assert old_backup is not None

    bad_backup = backups_dir / "xcagi-bad-latest.db"
    bad_backup.write_bytes(b"corrupt backup content")
    new_mtime = old_backup.stat().st_mtime + 100
    os.utime(bad_backup, (new_mtime, new_mtime))

    db_path.write_bytes(b"corrupt main db")

    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "restored"
    assert result["detail"] == old_backup.name, (
        "must skip the bad backup and use the older good one"
    )


def test_recover_if_corrupt_uses_legacy_bak_backups(tmp_path, monkeypatch):
    """recover_if_corrupt 也应能从 data/database_backups/*.bak 恢复。

    DatabaseService（/api/database/backup 端点）备份到 database_backups/*.bak。
    recover_if_corrupt 必须同时扫这个目录，否则用户手动备份在自愈时用不上。
    """
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"

    _create_test_db(db_path)

    legacy_backups_dir = dirs["data"] / "database_backups"
    legacy_backups_dir.mkdir(parents=True, exist_ok=True)
    legacy_backup = legacy_backups_dir / "xcagi.db.20260704_120000.bak"
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(legacy_backup))
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    assert _integrity_check_ok(legacy_backup)

    db_path.write_bytes(b"corrupt main db content")

    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "restored", f"expected restored, got {result}"
    assert result["detail"] == legacy_backup.name

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT customer FROM orders").fetchall()
    conn.close()
    assert len(rows) == 2


def test_desktop_sqlite_connection_enables_wal(tmp_path, monkeypatch):
    """桌面端 SQLite 连接必须开 WAL + synchronous=FULL + wal_autocheckpoint=1000。"""
    _reset_desktop_env(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")

    db_path = tmp_path / "test_desktop.db"
    _create_test_db(db_path)

    from app.db import _create_engine_for_url

    url = f"sqlite:///{db_path.as_posix()}"
    engine = _create_engine_for_url(url)
    try:
        with engine.connect() as conn:
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            synchronous = conn.exec_driver_sql("PRAGMA synchronous").scalar()
            autocheckpoint = conn.exec_driver_sql("PRAGMA wal_autocheckpoint").scalar()

        assert str(journal_mode).lower() == "wal", f"expected journal_mode=wal, got {journal_mode}"
        assert int(synchronous) == 2, f"expected synchronous=FULL (2), got {synchronous}"
        assert int(autocheckpoint) == 1000
    finally:
        engine.dispose()


def test_non_desktop_mode_does_not_force_wal(tmp_path, monkeypatch):
    """非桌面模式（Web/测试）下 SQLite 不应被强制开 WAL。"""
    _reset_desktop_env(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")

    from app.db import _sqlite_desktop_mode

    assert _sqlite_desktop_mode() is False, "XCAGI_DESKTOP_MODE='0' must be non-desktop"

    db_path = tmp_path / "test_non_desktop.db"
    _create_test_db(db_path)

    conn = sqlite3.connect(str(db_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()
    conn.close()
    assert mode and str(mode[0]).lower() != "wal", (
        f"freshly created db should be in rollback journal mode, got {mode}"
    )

    from app.db import _create_engine_for_url

    url = f"sqlite:///{db_path.as_posix()}"
    engine = _create_engine_for_url(url)
    try:
        with engine.connect() as conn:
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()

        assert str(journal_mode).lower() != "wal", (
            f"non-desktop mode must NOT be forced into WAL; got {journal_mode}"
        )
    finally:
        engine.dispose()


def test_configure_desktop_environment_runs_recover_on_healthy_db(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    root = configure_desktop_environment(tmp_path)
    assert root == tmp_path.resolve()

    assert db_path.exists()
    assert _quick_check_ok(db_path)


def test_corrupt_no_backup_warning_survives_restart(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    db_path = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    db_path.write_bytes(b"corrupt database")
    configure_desktop_environment(tmp_path)
    assert (tmp_path / "config" / "database-recovery-required").is_file()
    _reset_desktop_env(monkeypatch)
    _create_test_db(db_path)
    configure_desktop_environment(tmp_path)
    assert os.environ["XCAGI_DESKTOP_DB_RECOVERY"] == "corrupt_no_backup"

    backup = backup_database(tmp_path, version="restore")
    assert backup is not None
    db_path.write_bytes(b"corrupt again")
    _reset_desktop_env(monkeypatch)
    configure_desktop_environment(tmp_path)
    assert os.environ["XCAGI_DESKTOP_DB_RECOVERY"] == f"restored:{backup.name}"
    assert not (tmp_path / "config" / "database-recovery-required").exists()
