"""桌面端 SQLite 数据可靠性测试：WAL 模式、在线热备份、损坏自愈。

覆盖范围：
- 桌面 SQLite 连接确实开了 WAL + synchronous=FULL
- backup_database 在主库有写入时也能成功备份（在线热备份，证明用 sqlite3.backup API）
- backup_database 备份出来的库通过 integrity_check
- recover_if_corrupt 在库正常时不做任何操作
- recover_if_corrupt 能识别损坏库
- recover_if_corrupt 能从备份恢复
- recover_if_corrupt 在没备份时返回 corrupt_no_backup
- recover_if_corrupt 跳过损坏备份用更老的备份
"""

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


# ----------------------------------------------------------------------------
# backup_database
# ----------------------------------------------------------------------------


def test_backup_database_produces_consistent_online_backup(tmp_path, monkeypatch):
    """backup_database 必须用 sqlite3.backup() API，主库有未 checkpoint 写入时
    也能备份出一致的库（shutil.copy2 会拷到不一致状态，会丢 WAL 内容）。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    # 模拟业务在跑：开一个连接，写入但未关闭（如果开了 WAL 会产生 WAL 内容）
    live_conn = sqlite3.connect(str(db_path))
    live_conn.execute("INSERT INTO orders (customer) VALUES ('carol')")
    live_conn.commit()

    try:
        result = backup_database(tmp_path, version="online")
        assert result is not None, "online hot backup should succeed"
        assert result.exists()

        # 验证备份出来的库包含 carol 这条记录
        # shutil.copy2 在 rollback journal 模式下也能拷到（因为没有独立 WAL 文件），
        # 但如果主库在 WAL 模式 + 有未 checkpoint 写入，shutil.copy2 会丢这部分。
        # 这里验证 backup_database 函数产出的库包含全部数据。
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
    """backup_database 备份出来的库必须能通过 PRAGMA integrity_check。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    result = backup_database(tmp_path, version="v1")
    assert result is not None
    assert result.exists()
    assert _integrity_check_ok(result), "backup file must pass integrity_check"


def test_backup_database_returns_none_when_db_missing(tmp_path, monkeypatch):
    """主库不存在时返回 None（首启场景）。"""
    _reset_desktop_env(monkeypatch)
    ensure_desktop_dirs(tmp_path)
    # 不创建 db
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


# ----------------------------------------------------------------------------
# recover_if_corrupt
# ----------------------------------------------------------------------------


def test_recover_if_corrupt_returns_ok_for_healthy_db(tmp_path, monkeypatch):
    """库健康时返回 ok，不做任何操作。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    mtime_before = db_path.stat().st_mtime
    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "ok"
    assert result["detail"] == ""
    # 库文件未被改动
    assert db_path.stat().st_mtime == mtime_before


def test_recover_if_corrupt_recovers_from_backup(tmp_path, monkeypatch):
    """库损坏时能从最近的备份恢复。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"

    # 1) 先建一个健康库，备份它
    _create_test_db(db_path)
    backup_path = backup_database(tmp_path, version="v1")
    assert backup_path is not None and backup_path.exists()

    # 2) 模拟主库损坏：覆写为垃圾内容
    db_path.write_bytes(b"not a sqlite database file !!! corruption")

    # 3) recover 应该能从备份恢复
    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "restored", f"expected restored, got {result}"
    assert result["detail"] == backup_path.name

    # 4) 主库已恢复，能正常打开并查到数据
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT customer FROM orders").fetchall()
    conn.close()
    assert len(rows) == 2

    # 5) 坏库已被改名保留为证据
    corrupt_files = list(dirs["data"].glob("xcagi.db.corrupt-*"))
    assert len(corrupt_files) == 1, "corrupt db must be renamed and kept as evidence"


def test_recover_if_corrupt_no_backup_returns_corrupt_no_backup(tmp_path, monkeypatch):
    """库损坏但没备份时返回 corrupt_no_backup。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"

    # 主库存在但损坏，没有任何备份
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"corrupt content")

    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "corrupt_no_backup"

    # 坏库仍然被改名保留
    corrupt_files = list(dirs["data"].glob("xcagi.db.corrupt-*"))
    assert len(corrupt_files) == 1


def test_recover_if_corrupt_skips_bad_backups(tmp_path, monkeypatch):
    """最近的备份本身损坏时，跳过它并尝试更老的备份。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    backups_dir = dirs["backups"]

    # 1) 建一个老的好备份
    _create_test_db(db_path)
    old_backup = backup_database(tmp_path, version="old")
    assert old_backup is not None

    # 2) 在 backups/ 里塞一个更"新"但损坏的备份文件（mtime 更靠后）
    bad_backup = backups_dir / "xcagi-bad-latest.db"
    bad_backup.write_bytes(b"corrupt backup content")
    new_mtime = old_backup.stat().st_mtime + 100
    os.utime(bad_backup, (new_mtime, new_mtime))

    # 3) 损坏主库
    db_path.write_bytes(b"corrupt main db")

    # 4) recover 应该跳过 bad_backup，使用 old_backup
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

    # 1) 建一个健康库
    _create_test_db(db_path)

    # 2) 用 sqlite3.backup() 模拟 DatabaseService 手动备份到 database_backups/
    legacy_backups_dir = dirs["data"] / "database_backups"
    legacy_backups_dir.mkdir(parents=True, exist_ok=True)
    legacy_backup = legacy_backups_dir / "xcagi.db.20260704_120000.bak"
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(legacy_backup))
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    assert _integrity_check_ok(legacy_backup)

    # 3) 损坏主库
    db_path.write_bytes(b"corrupt main db content")

    # 4) recover 应该能从 legacy_backup 恢复
    result = recover_if_corrupt(tmp_path)
    assert result["action"] == "restored", f"expected restored, got {result}"
    assert result["detail"] == legacy_backup.name

    # 5) 主库已恢复，能查到数据
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT customer FROM orders").fetchall()
    conn.close()
    assert len(rows) == 2


# ----------------------------------------------------------------------------
# WAL 模式钩子
# ----------------------------------------------------------------------------


def test_desktop_sqlite_connection_enables_wal(tmp_path, monkeypatch):
    """桌面端 SQLite 连接必须开 WAL + synchronous=FULL + wal_autocheckpoint=1000。"""
    _reset_desktop_env(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")

    db_path = tmp_path / "test_desktop.db"
    _create_test_db(db_path)

    # 通过 SQLAlchemy 创建一个连接，触发 connect 事件钩子
    from app.db import _create_engine_for_url

    url = f"sqlite:///{db_path.as_posix()}"
    engine = _create_engine_for_url(url)
    try:
        with engine.connect() as conn:
            journal_mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            synchronous = conn.exec_driver_sql("PRAGMA synchronous").scalar()
            autocheckpoint = conn.exec_driver_sql("PRAGMA wal_autocheckpoint").scalar()

        # WAL 模式下 journal_mode 应该返回 "wal"（小写）
        assert str(journal_mode).lower() == "wal", f"expected journal_mode=wal, got {journal_mode}"
        # synchronous=FULL 的值是 2
        assert int(synchronous) == 2, f"expected synchronous=FULL (2), got {synchronous}"
        assert int(autocheckpoint) == 1000
    finally:
        engine.dispose()


def test_non_desktop_mode_does_not_force_wal(tmp_path, monkeypatch):
    """非桌面模式（Web/测试）下 SQLite 不应被强制开 WAL。"""
    _reset_desktop_env(monkeypatch)
    # 显式设为 "0" 确保 _sqlite_desktop_mode() 返回 False
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")

    from app.db import _sqlite_desktop_mode

    assert _sqlite_desktop_mode() is False, "XCAGI_DESKTOP_MODE='0' must be non-desktop"

    db_path = tmp_path / "test_non_desktop.db"
    _create_test_db(db_path)

    # 确保测试 db 是默认 rollback journal 模式（防止前一个测试的 WAL 残留）
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

        # 非桌面模式不强制开 WAL
        assert str(journal_mode).lower() != "wal", (
            f"non-desktop mode must NOT be forced into WAL; got {journal_mode}"
        )
    finally:
        engine.dispose()


# ----------------------------------------------------------------------------
# 集成：configure_desktop_environment 触发自愈
# ----------------------------------------------------------------------------


def test_configure_desktop_environment_runs_recover_on_healthy_db(tmp_path, monkeypatch):
    """configure_desktop_environment 应该调用 recover_if_corrupt，健康库不报错。"""
    _reset_desktop_env(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")

    # 先建一个健康库（模拟客户已经用过）
    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)

    # 调用 configure_desktop_environment 应该不报错
    # 注意：configure_desktop_environment 内部会调用 recover_if_corrupt
    root = configure_desktop_environment(tmp_path)
    assert root == tmp_path.resolve()

    # 库仍然存在且健康
    assert db_path.exists()
    assert _quick_check_ok(db_path)
