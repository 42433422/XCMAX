"""桌面 SQLite 备份、恢复和连接行为测试。"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from app.desktop_runtime.desktop_runtime_paths import (
    configure_desktop_environment,
    ensure_desktop_dirs,
)
from app.desktop_runtime.migrate import (
    _integrity_check_ok,
    _quick_check_ok,
    backup_database,
    recover_if_corrupt,
)


def _create_test_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT)")
    conn.execute("INSERT INTO orders (customer) VALUES ('alice'), ('bob')")
    conn.commit()
    conn.close()


def _reset_desktop_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DB_RECOVERY", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)


def test_backup_database_produces_consistent_online_backup(tmp_path, monkeypatch):
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


def test_recovery_quarantines_crashed_wal_before_restoring_backup(tmp_path, monkeypatch):
    from app.desktop_runtime import migrate

    _reset_desktop_env(monkeypatch)
    dirs = ensure_desktop_dirs(tmp_path)
    db = dirs["data"] / "xcagi.db"
    _create_test_db(db)
    backup = backup_database(tmp_path, version="before-crash")
    assert backup is not None
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sqlite3, sys; db = sqlite3.connect(sys.argv[1]); "
            "db.execute('PRAGMA journal_mode=WAL'); "
            "db.execute('PRAGMA wal_autocheckpoint=0'); "
            "db.execute(\"UPDATE orders SET customer='stale-wal'\"); "
            "db.commit(); os._exit(0)",
            str(db),
        ],
        check=True,
        timeout=30,
    )
    original_wal = Path(f"{db}-wal").read_bytes()
    with db.open("r+b") as stream:
        stream.write(b"corrupt sqlite!!")
    corrupt_bytes = db.read_bytes()
    sidecars = {}
    original_check = migrate._quick_check_ok

    def capture_checked_image(path):
        valid = original_check(path)
        # SQLite may rebuild its shared-memory index during the health check.
        # Freeze those exact bytes before recovery quarantines the whole image.
        sidecars.update({suffix: Path(f"{db}{suffix}").read_bytes() for suffix in ("-wal", "-shm")})
        return valid

    monkeypatch.setattr(migrate, "_quick_check_ok", capture_checked_image)

    result = recover_if_corrupt(tmp_path)

    assert result == {"action": "restored", "detail": backup.name}
    assert sidecars["-wal"] == original_wal
    with closing(sqlite3.connect(db)) as restored:
        assert restored.execute("SELECT customer FROM orders ORDER BY id").fetchall() == [
            ("alice",),
            ("bob",),
        ]
        assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    originals = [
        path
        for path in dirs["data"].glob("xcagi.db.corrupt-*")
        if path.read_bytes() == corrupt_bytes
    ]
    assert len(originals) == 1
    for suffix, content in sidecars.items():
        assert Path(f"{originals[0]}{suffix}").read_bytes() == content
        assert not Path(f"{db}{suffix}").exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_recovery_stops_when_corrupt_sidecar_cannot_be_quarantined(tmp_path, monkeypatch, suffix):
    _reset_desktop_env(monkeypatch)
    dirs = ensure_desktop_dirs(tmp_path)
    db = dirs["data"] / "xcagi.db"
    _create_test_db(db)
    backup = backup_database(tmp_path, version="before-crash")
    assert backup is not None
    db.write_bytes(b"corrupt original")
    sidecar = Path(f"{db}{suffix}")
    sidecar.write_bytes(b"original journal evidence")
    original_rename = Path.rename

    def fail_sidecar_rename(path, target):
        if path == sidecar:
            raise OSError("sidecar is locked")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_sidecar_rename)
    result = recover_if_corrupt(tmp_path)

    assert result["action"] == "corrupt_no_backup"
    assert not db.exists()
    assert sidecar.read_bytes() == b"original journal evidence"
    originals = list(dirs["data"].glob("xcagi.db.corrupt-*"))
    assert len(originals) == 1 and originals[0].read_bytes() == b"corrupt original"
    assert _integrity_check_ok(backup)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_recovery_preserves_previous_sidecar_evidence(tmp_path, monkeypatch, suffix):
    from app.desktop_runtime import migrate

    _reset_desktop_env(monkeypatch)
    db = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    db.write_bytes(b"corrupt original")
    Path(f"{db}{suffix}").write_bytes(b"current journal")
    monkeypatch.setattr(migrate, "utc_now_naive", lambda: datetime(2026, 11, 24, 0, 0, 0))
    earlier = db.with_name(f"xcagi.db.corrupt-20261124000000{suffix}")
    earlier.write_bytes(b"previous journal")

    assert recover_if_corrupt(tmp_path)["action"] == "corrupt_no_backup"

    assert earlier.read_bytes() == b"previous journal"
    quarantine = db.with_name("xcagi.db.corrupt-20261124000000-1")
    assert quarantine.read_bytes() == b"corrupt original"
    assert Path(f"{quarantine}{suffix}").read_bytes() == b"current journal"


def test_recovery_never_publishes_backup_corrupted_after_check(tmp_path, monkeypatch):
    from app.desktop_runtime import migrate

    _reset_desktop_env(monkeypatch)
    dirs = ensure_desktop_dirs(tmp_path)
    db = dirs["data"] / "xcagi.db"
    _create_test_db(db)
    backup = backup_database(tmp_path, version="before-crash")
    assert backup is not None
    db.write_bytes(b"corrupt original")
    original_check = migrate._integrity_check_ok

    def corrupt_after_check(path):
        valid = original_check(path)
        if path == backup:
            assert valid
            path.write_bytes(b"backup became corrupt")
        return valid

    monkeypatch.setattr(migrate, "_integrity_check_ok", corrupt_after_check)
    result = recover_if_corrupt(tmp_path)

    assert result["action"] == "corrupt_no_backup"
    assert not db.exists()
    assert backup.read_bytes() == b"backup became corrupt"
    assert list(dirs["data"].glob("xcagi.db.corrupt-*"))[0].read_bytes() == b"corrupt original"
    assert not list(dirs["data"].glob("xcagi-recovery-*"))


def test_recovery_waits_for_existing_migration_lock(tmp_path, monkeypatch):
    from app.desktop_runtime.migrate import migration_lock

    _reset_desktop_env(monkeypatch)
    db = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    _create_test_db(db)
    backup = backup_database(tmp_path, version="before-crash")
    assert backup is not None
    db.write_bytes(b"original database under migration")
    started = threading.Event()

    def recover():
        started.set()
        return recover_if_corrupt(tmp_path)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with migration_lock(tmp_path):
            pending = pool.submit(recover)
            assert started.wait(5)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.25)
            assert db.read_bytes() == b"original database under migration"
        assert pending.result(timeout=5) == {"action": "restored", "detail": backup.name}


def test_recovery_io_failure_sets_existing_persistent_warning(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    db = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    _create_test_db(db)
    backup = backup_database(tmp_path, version="before-crash")
    assert backup is not None
    backup_bytes = backup.read_bytes()
    db.write_bytes(b"corrupt original")
    original_stat = Path.stat

    def inaccessible_backup_stat(path, *args, **kwargs):
        if path == backup:
            raise OSError("backup storage became unavailable")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", inaccessible_backup_stat)
    configure_desktop_environment(tmp_path)

    assert os.environ.get("XCAGI_DESKTOP_DB_RECOVERY") == "corrupt_no_backup"
    assert (tmp_path / "config" / "database-recovery-required").is_file()
    assert not db.exists()
    assert backup.read_bytes() == backup_bytes
    assert list(db.parent.glob("xcagi.db.corrupt-*"))[0].read_bytes() == b"corrupt original"


def test_recovery_hard_exit_after_rename_cannot_become_fresh_start(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    db = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    db.write_bytes(b"customer database awaiting recovery")
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys\n"
            "from pathlib import Path\n"
            "from app.desktop_runtime.migrate import recover_if_corrupt\n"
            "rename = Path.rename\n"
            "def crash_after_rename(path, target):\n"
            "    result = rename(path, target)\n"
            "    if path.name == 'xcagi.db': os._exit(93)\n"
            "    return result\n"
            "Path.rename = crash_after_rename\n"
            "recover_if_corrupt(sys.argv[1])\n",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert crashed.returncode == 93, crashed.stderr
    assert not db.exists()

    configure_desktop_environment(tmp_path)

    assert os.environ.get("XCAGI_DESKTOP_DB_RECOVERY") == "corrupt_no_backup"
    assert (tmp_path / "config" / "database-recovery-required").is_file()
    assert not db.exists()
    assert list(db.parent.glob("xcagi.db.corrupt-*"))[0].read_bytes() == (
        b"customer database awaiting recovery"
    )


def test_recovery_published_snapshot_is_not_replaced_after_cleanup_failure(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    db = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    _create_test_db(db)
    old_backup = backup_database(tmp_path, version="old")
    assert old_backup is not None
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("UPDATE orders SET customer='latest-backup'")
        connection.commit()
    latest = backup_database(tmp_path, version="latest")
    assert latest is not None
    stamp = old_backup.stat().st_mtime + 100
    os.utime(latest, (stamp, stamp))
    db.write_bytes(b"corrupt original")
    cleanup = tempfile.TemporaryDirectory.cleanup
    failures = []

    def fail_first_cleanup(directory):
        cleanup(directory)
        if Path(directory.name).name.startswith("xcagi-recovery-") and not failures:
            failures.append(directory.name)
            raise OSError("temporary recovery cleanup failed")

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", fail_first_cleanup)
    result = recover_if_corrupt(tmp_path)

    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT customer FROM orders ORDER BY id").fetchall() == [
            ("latest-backup",),
            ("latest-backup",),
        ]
    assert result["action"] == "corrupt_no_backup"
    assert (tmp_path / "config" / "database-recovery-required").exists()
    assert len(failures) == 1 and old_backup.exists() and latest.exists()


def test_recovery_marker_cleanup_failure_keeps_verified_database_blocked(tmp_path, monkeypatch):
    _reset_desktop_env(monkeypatch)
    db = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    _create_test_db(db)
    assert backup_database(tmp_path, version="before-crash") is not None
    db.write_bytes(b"corrupt original")
    marker = tmp_path / "config" / "database-recovery-required"
    unlink = Path.unlink

    def fail_marker_clear(path, *args, **kwargs):
        if path == marker:
            raise PermissionError("recovery marker is locked")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_marker_clear)
    assert recover_if_corrupt(tmp_path)["action"] == "corrupt_no_backup"
    assert marker.is_file()
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT customer FROM orders ORDER BY id").fetchall() == [
            ("alice",),
            ("bob",),
        ]
    configure_desktop_environment(tmp_path)
    assert os.environ.get("XCAGI_DESKTOP_DB_RECOVERY") == "corrupt_no_backup"
    assert marker.is_file()


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


@pytest.mark.parametrize(
    "backup_content", [b"corrupt backup content", b"", pytest.param(None, id="empty-schema")]
)
def test_recover_if_corrupt_skips_bad_backups(tmp_path, monkeypatch, backup_content):
    """最近的备份本身损坏时，跳过它并尝试更老的备份。"""
    _reset_desktop_env(monkeypatch)

    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    backups_dir = dirs["backups"]

    _create_test_db(db_path)
    old_backup = backup_database(tmp_path, version="old")
    assert old_backup is not None

    bad_backup = backups_dir / "xcagi-bad-latest.db"
    if backup_content is None:
        _create_test_db(bad_backup)
        with closing(sqlite3.connect(bad_backup)) as connection:
            connection.execute("DROP TABLE orders")
            connection.commit()
            assert connection.execute("PRAGMA page_count").fetchone()[0] >= 2
        assert _integrity_check_ok(bad_backup)
    else:
        bad_backup.write_bytes(backup_content)
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


def test_backup_restore_keeps_rows_mods_and_config(tmp_path, monkeypatch):
    """升级/回滚数据面：热备份能还原已提交行，旁边的 Mod 与配置文件不被覆盖。"""
    _reset_desktop_env(monkeypatch)
    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)
    mod_file = dirs["mods"] / "sample-mod" / "mod.json"
    mod_file.parent.mkdir(parents=True)
    mod_file.write_text('{"id":"sample-mod","keep":true}', encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text('{"sku":"enterprise"}', encoding="utf-8")

    backup = backup_database(tmp_path, version="1.0.0.7")
    assert backup is not None
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM orders")
        conn.commit()
    db_path.write_bytes(b"this is not a sqlite database")

    restored = recover_if_corrupt(tmp_path)
    assert restored["action"] == "restored"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert json_ok(mod_file.read_text(encoding="utf-8"))
    assert config_file.read_text(encoding="utf-8").startswith("{")


def json_ok(text: str) -> bool:
    return text.startswith("{") and "sample-mod" in text


def test_newer_schema_refuses_blind_downgrade_and_keeps_rows(tmp_path, monkeypatch):
    """库内迁移戳比当前包新时，升级路径保持原戳，不重放、不改已有行、Mod 和配置。"""
    from app.desktop_runtime.migrate import repair_unknown_stamped_revision, run_alembic_upgrade

    _reset_desktop_env(monkeypatch)
    dirs = ensure_desktop_dirs(tmp_path)
    db_path = dirs["data"] / "xcagi.db"
    _create_test_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(
            "INSERT INTO alembic_version (version_num) VALUES ('2099_01_01_future_irreversible')"
        )
        conn.commit()
    mod_file = dirs["mods"] / "sample-mod" / "mod.json"
    mod_file.parent.mkdir(parents=True)
    mod_file.write_text('{"id":"sample-mod","keep":true}', encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text('{"sku":"enterprise"}', encoding="utf-8")

    repair = repair_unknown_stamped_revision(tmp_path)
    assert repair is not None
    assert repair["action"] == "newer_than_package"
    run_alembic_upgrade(tmp_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "2099_01_01_future_irreversible"
        )
        assert conn.execute("SELECT customer FROM orders ORDER BY id").fetchall() == [
            ("alice",),
            ("bob",),
        ]
    assert mod_file.read_text(encoding="utf-8").startswith("{")
    assert config_file.read_text(encoding="utf-8").startswith("{")
