"""桌面端定时备份调度器测试。

覆盖：
- _has_backup_today：识别今天的定时备份文件名
- _cleanup_old_backups：清理超期备份，保留近期
- get_last_backup_info：跨 backups/ 和 database_backups/ 取最新
- start/stop_backup_scheduler：幂等启动、优雅停止、非桌面模式不启动
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.desktop_runtime.backup_scheduler import (
    _cleanup_old_backups,
    _has_backup_today,
    _make_weekly_copy,
    _sync_to_external,
    get_last_backup_info,
    start_backup_scheduler,
    stop_backup_scheduler,
)
from app.desktop_runtime.paths import ensure_desktop_dirs


def _reset_desktop_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
    monkeypatch.delenv("XCAGI_DESKTOP_DB_RECOVERY", raising=False)


def _make_backup_file(backups_dir: Path, version: str, stamp: str) -> Path:
    """在 backups/ 创建一个名为 xcagi-{version}-{stamp}.db 的占位备份。"""
    backups_dir.mkdir(parents=True, exist_ok=True)
    p = backups_dir / f"xcagi-{version}-{stamp}.db"
    p.write_bytes(b"placeholder")
    return p


def _make_legacy_backup(legacy_dir: Path, name: str) -> Path:
    """在 database_backups/ 创建一个 .bak 占位备份（DatabaseService 手动备份格式）。"""
    legacy_dir.mkdir(parents=True, exist_ok=True)
    p = legacy_dir / name
    p.write_bytes(b"placeholder")
    return p


# ----------------------------------------------------------------------------
# _has_backup_today
# ----------------------------------------------------------------------------


class TestHasBackupToday:
    def test_returns_true_when_today_backup_exists(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        today = datetime.now().strftime("%Y%m%d")
        _make_backup_file(dirs["backups"], "v1", f"{today}120000")

        assert _has_backup_today(dirs["backups"]) is True

    def test_returns_false_when_only_yesterday_backup(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        _make_backup_file(dirs["backups"], "v1", f"{yesterday}120000")

        assert _has_backup_today(dirs["backups"]) is False

    def test_returns_false_when_empty_dir(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)

        assert _has_backup_today(dirs["backups"]) is False

    def test_ignores_non_xcagi_prefixed_files(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        today = datetime.now().strftime("%Y%m%d")
        # 不匹配 xcagi-*.db 模式的文件不应被当作定时备份
        (dirs["backups"] / f"other-{today}120000.db").write_bytes(b"x")

        assert _has_backup_today(dirs["backups"]) is False


# ----------------------------------------------------------------------------
# _cleanup_old_backups
# ----------------------------------------------------------------------------


class TestCleanupOldBackups:
    def test_removes_old_backups_keeps_recent(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        backups_dir = dirs["backups"]

        old_stamp = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d%H%M%S")
        recent_stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        old_file = _make_backup_file(backups_dir, "v1", old_stamp)
        recent_file = _make_backup_file(backups_dir, "v1", recent_stamp)
        # 老 backup 的 mtime 也要设到 10 天前
        old_ts = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(old_file, (old_ts, old_ts))

        _cleanup_old_backups(backups_dir, retention_days=7)

        assert not old_file.exists(), "old backup should be removed"
        assert recent_file.exists(), "recent backup should be kept"

    def test_does_not_touch_bak_files(self, tmp_path, monkeypatch):
        """清理只动 xcagi-*.db（定时备份），不动 *.bak（用户手动备份）。"""
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        backups_dir = dirs["backups"]

        old_ts = (datetime.now() - timedelta(days=30)).timestamp()
        old_bak = backups_dir / "manual.bak"
        old_bak.write_bytes(b"x")
        os.utime(old_bak, (old_ts, old_ts))

        _cleanup_old_backups(backups_dir, retention_days=7)

        assert old_bak.exists(), "manual .bak backups must not be cleaned up"

    def test_empty_dir_is_noop(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)

        # 不应抛异常
        _cleanup_old_backups(dirs["backups"], retention_days=7)


# ----------------------------------------------------------------------------
# get_last_backup_info
# ----------------------------------------------------------------------------


class TestGetLastBackupInfo:
    def test_returns_none_fields_when_no_backups(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)

        info = get_last_backup_info(dirs["root"])

        assert info["path"] is None
        assert info["timestamp"] is None
        assert info["size"] is None

    def test_returns_latest_from_backups_dir(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        old = _make_backup_file(dirs["backups"], "v1", "20260101000000")
        time.sleep(0.05)
        recent = _make_backup_file(dirs["backups"], "v1", "20260705000000")

        info = get_last_backup_info(dirs["root"])

        assert info["filename"] == recent.name
        assert info["size"] == recent.stat().st_size

    def test_returns_latest_across_both_dirs(self, tmp_path, monkeypatch):
        """get_last_backup_info 应同时扫 backups/ 和 database_backups/，取最新。"""
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        # backups/ 里放一个旧的
        _make_backup_file(dirs["backups"], "v1", "20260101000000")
        time.sleep(0.05)
        # database_backups/ 里放一个更新的 .bak
        legacy_dir = dirs["data"] / "database_backups"
        _make_legacy_backup(legacy_dir, "xcagi.db.20260705_120000.bak")

        info = get_last_backup_info(dirs["root"])

        assert "xcagi.db" in info["filename"]
        assert info["filename"].endswith(".bak")


# ----------------------------------------------------------------------------
# start/stop_backup_scheduler
# ----------------------------------------------------------------------------


class TestSchedulerLifecycle:
    def test_does_not_start_in_non_desktop_mode(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        # XCAGI_DESKTOP_MODE 未设置，不应启动
        start_backup_scheduler(tmp_path)
        stop_backup_scheduler()

    def test_does_not_start_for_postgres(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")

        start_backup_scheduler(tmp_path)
        stop_backup_scheduler()
        # 没有线程被创建，stop 是 no-op，不抛异常即通过

    def test_starts_in_desktop_sqlite_mode(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")

        try:
            start_backup_scheduler(tmp_path)
            # 幂等：再调一次不会创建第二个线程
            start_backup_scheduler(tmp_path)
        finally:
            stop_backup_scheduler(timeout=1.0)

    def test_stop_is_noop_when_not_started(self):
        # 没启动过直接 stop 不应抛异常
        stop_backup_scheduler()


# ----------------------------------------------------------------------------
# _make_weekly_copy
# ----------------------------------------------------------------------------


class TestMakeWeeklyCopy:
    def test_creates_weekly_copy_with_correct_name(self, tmp_path, monkeypatch):
        """weekly 副本文件名格式：xcagi-{version}-weekly-{stamp}.db"""
        _reset_desktop_env(monkeypatch)
        daily = tmp_path / "xcagi-10.0.0-20260705123000.db"
        daily.write_bytes(b"backup-content")

        result = _make_weekly_copy(daily)

        assert result is not None
        assert result.name == "xcagi-10.0.0-weekly-20260705123000.db"
        assert result.exists()
        assert result.read_bytes() == b"backup-content"

    def test_returns_none_for_already_weekly_file(self, tmp_path, monkeypatch):
        """已经是 weekly 的文件不应再复制一次。"""
        _reset_desktop_env(monkeypatch)
        weekly = tmp_path / "xcagi-10.0.0-weekly-20260705123000.db"
        weekly.write_bytes(b"x")

        result = _make_weekly_copy(weekly)

        assert result is None

    def test_returns_none_for_malformed_name(self, tmp_path, monkeypatch):
        """文件名不符合 xcagi-{version}-{stamp}.db 格式时返回 None。"""
        _reset_desktop_env(monkeypatch)
        bad = tmp_path / "random.db"
        bad.write_bytes(b"x")

        result = _make_weekly_copy(bad)

        assert result is None


# ----------------------------------------------------------------------------
# _sync_to_external
# ----------------------------------------------------------------------------


class TestSyncToExternal:
    def test_noop_when_env_not_set(self, tmp_path, monkeypatch):
        """未配置 XCAGI_EXTERNAL_BACKUP_DIR 时不同步。"""
        _reset_desktop_env(monkeypatch)
        monkeypatch.delenv("XCAGI_EXTERNAL_BACKUP_DIR", raising=False)
        backup = tmp_path / "xcagi-10.0.0-20260705123000.db"
        backup.write_bytes(b"x")

        _sync_to_external(backup)  # 不应抛异常

    def test_copies_to_external_dir(self, tmp_path, monkeypatch):
        """配置了外部目录时，备份文件被复制过去。"""
        _reset_desktop_env(monkeypatch)
        external = tmp_path / "usb"
        monkeypatch.setenv("XCAGI_EXTERNAL_BACKUP_DIR", str(external))
        backup = tmp_path / "xcagi-10.0.0-20260705123000.db"
        backup.write_bytes(b"backup-content")

        _sync_to_external(backup)

        dest = external / backup.name
        assert dest.exists()
        assert dest.read_bytes() == b"backup-content"

    def test_warns_when_external_unavailable(self, tmp_path, monkeypatch, caplog):
        """外部目录不可写（如 USB 未插入）时仅警告，不抛异常。"""
        _reset_desktop_env(monkeypatch)
        # 指向一个不存在的根路径，mkdir 会失败（在 macOS/Linux 上模拟）
        monkeypatch.setenv("XCAGI_EXTERNAL_BACKUP_DIR", "/nonexistent-root-xyz/usb")
        backup = tmp_path / "xcagi-10.0.0-20260705123000.db"
        backup.write_bytes(b"x")

        # 不应抛异常
        _sync_to_external(backup)


# ----------------------------------------------------------------------------
# _cleanup_old_backups — weekly 保留策略
# ----------------------------------------------------------------------------


class TestCleanupWeeklyBackups:
    def test_weekly_backup_kept_beyond_daily_retention(self, tmp_path, monkeypatch):
        """weekly 备份在 7 天后不应被清理（保留 28 天）。"""
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        backups_dir = dirs["backups"]

        # 10 天前的 weekly 备份（超过 daily 7 天，但小于 weekly 28 天）
        old_stamp = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d%H%M%S")
        weekly_file = backups_dir / f"xcagi-10.0.0-weekly-{old_stamp}.db"
        weekly_file.write_bytes(b"x")
        old_ts = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(weekly_file, (old_ts, old_ts))

        _cleanup_old_backups(backups_dir, retention_days=7)

        assert weekly_file.exists(), "weekly backup should be kept (within 28-day retention)"

    def test_weekly_backup_removed_after_28_days(self, tmp_path, monkeypatch):
        """weekly 备份超过 28 天应被清理。"""
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        backups_dir = dirs["backups"]

        old_stamp = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d%H%M%S")
        weekly_file = backups_dir / f"xcagi-10.0.0-weekly-{old_stamp}.db"
        weekly_file.write_bytes(b"x")
        old_ts = (datetime.now() - timedelta(days=30)).timestamp()
        os.utime(weekly_file, (old_ts, old_ts))

        _cleanup_old_backups(backups_dir, retention_days=7)

        assert not weekly_file.exists(), "weekly backup older than 28 days should be removed"

    def test_daily_and_weekly_cleaned_independently(self, tmp_path, monkeypatch):
        """daily 7 天清理，weekly 28 天清理，两者独立。"""
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        backups_dir = dirs["backups"]

        # 10 天前的 daily（应被清理）
        daily_stamp = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d%H%M%S")
        daily_file = backups_dir / f"xcagi-10.0.0-{daily_stamp}.db"
        daily_file.write_bytes(b"x")
        daily_ts = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(daily_file, (daily_ts, daily_ts))

        # 10 天前的 weekly（应保留）
        weekly_file = backups_dir / f"xcagi-10.0.0-weekly-{daily_stamp}.db"
        weekly_file.write_bytes(b"x")
        os.utime(weekly_file, (daily_ts, daily_ts))

        _cleanup_old_backups(backups_dir, retention_days=7)

        assert not daily_file.exists(), "daily backup older than 7 days should be removed"
        assert weekly_file.exists(), "weekly backup within 28 days should be kept"


# ----------------------------------------------------------------------------
# _has_backup_today — weekly 也算今天的备份
# ----------------------------------------------------------------------------


class TestHasBackupTodayWeekly:
    def test_weekly_backup_counts_as_today(self, tmp_path, monkeypatch):
        """今天的 weekly 备份也应算"今天已备份"，避免周日重复跑 daily。"""
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        today = datetime.now().strftime("%Y%m%d")
        (dirs["backups"] / f"xcagi-10.0.0-weekly-{today}120000.db").write_bytes(b"x")

        assert _has_backup_today(dirs["backups"]) is True


class TestVersionedBackupNameParsing:
    def test_has_backup_today_supports_hyphenated_version(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        today = datetime.now().strftime("%Y%m%d")
        _make_backup_file(dirs["backups"], "1.0.0-rc.1", f"{today}120000")

        assert _has_backup_today(dirs["backups"]) is True

    def test_has_backup_today_rejects_missing_version(self, tmp_path, monkeypatch):
        _reset_desktop_env(monkeypatch)
        dirs = ensure_desktop_dirs(tmp_path)
        today = datetime.now().strftime("%Y%m%d")
        (dirs["backups"] / f"xcagi-{today}120000.db").write_bytes(b"x")

        assert _has_backup_today(dirs["backups"]) is False

    def test_weekly_copy_supports_hyphenated_version(self, tmp_path):
        daily = tmp_path / "xcagi-1.0.0-beta-20260705123000.db"
        daily.write_bytes(b"backup")

        weekly = _make_weekly_copy(daily)

        assert weekly is not None
        assert weekly.name == "xcagi-1.0.0-beta-weekly-20260705123000.db"
        assert weekly.read_bytes() == b"backup"

    def test_initial_delay_produces_backup_during_short_sessions(self):
        from app.desktop_runtime.backup_scheduler import _INITIAL_DELAY_SECONDS

        assert _INITIAL_DELAY_SECONDS == 10
