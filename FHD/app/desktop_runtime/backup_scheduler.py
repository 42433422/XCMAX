"""桌面端定时备份调度器。

桌面模式 + SQLite 下，FastAPI lifespan 启动一个 daemon 线程：
1. 启动后延迟几分钟（避开启动 IO 高峰）
2. 检查今天是否已有备份，没有则立即备份一次
3. 周日额外创建一份 weekly 备份（保留 4 周，满足灾备硬约束）
4. 之后每 24 小时备份一次
5. 清理超期备份，并把本地自动备份限制为最近 2 份
6. 若配置了 ``XCAGI_EXTERNAL_BACKUP_DIR``（如 USB 盘），同步复制到外部目录
7. 主进程退出时通过 Event 信号让线程优雅退出

不引入新依赖，仅用 threading。Celery/Redis 在桌面模式已禁用，不能依赖。
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .backup_retention import (
    AUTOMATIC_BACKUP_RE,
    DEFAULT_DAILY_RETENTION_DAYS,
    DEFAULT_WEEKLY_RETENTION_DAYS,
    WEEKLY_MARKER,
    cleanup_local_backups,
)
from .migrate import backup_database
from .paths import ensure_desktop_dirs, is_desktop_mode

logger = logging.getLogger(__name__)

# 启动后短暂延迟备份，避开 lifespan 的数据库迁移与路由装载高峰。
# 180 秒会让短时使用场景长期没有首份备份；桌面 runtime 通常在 2 秒内 ready。
_INITIAL_DELAY_SECONDS = 10
# 循环检查间隔。不到 24h 也可，但每次循环会判断"今天是否已备份"，
# 所以频繁检查不会导致频繁备份。
_POLL_INTERVAL_SECONDS = 3600
# daily 备份保留天数（按 mtime 清理）。
_RETENTION_DAYS = DEFAULT_DAILY_RETENTION_DAYS
# weekly 备份保留天数（周日额外创建一份，保留 4 周，满足灾备硬约束）。
_RETENTION_WEEKLY_DAYS = DEFAULT_WEEKLY_RETENTION_DAYS
# 周日额外创建 weekly 备份的文件名标记。
_WEEKLY_MARKER = WEEKLY_MARKER
# xcagi-{version}-{stamp}.db / xcagi-{version}-weekly-{stamp}.db。
# version 允许包含连字符，例如 1.0.0-beta 或 1.0.0-rc.1。
_BACKUP_STAMP_RE = AUTOMATIC_BACKUP_RE

_lock = threading.Lock()
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def start_backup_scheduler(data_dir: str | os.PathLike[str] | None = None) -> None:
    """启动定时备份后台线程。仅在桌面模式 + SQLite 下生效。

    幂等：重复调用不会启动多个线程。
    """
    global _stop_event, _thread

    if not is_desktop_mode():
        return

    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url.startswith("sqlite"):
        return

    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event = threading.Event()
        _thread = threading.Thread(
            target=_scheduler_loop,
            args=(_stop_event, data_dir),
            name="xcagi-backup-scheduler",
            daemon=True,
        )
        _thread.start()
        logger.info("desktop backup scheduler started")


def stop_backup_scheduler(timeout: float = 5.0) -> None:
    """通知调度线程退出并等待。FastAPI shutdown 时调用。"""
    global _stop_event, _thread

    with _lock:
        if _stop_event is None or _thread is None:
            return
        _stop_event.set()
        _thread.join(timeout=timeout)
        _stop_event = None
        _thread = None
        logger.info("desktop backup scheduler stopped")


def _scheduler_loop(stop_event: threading.Event, data_dir: str | os.PathLike[str] | None) -> None:
    """调度循环：延迟 → 检查今天是否已备份 → 备份 → 清理 → 等待下一轮。"""
    # 启动延迟：让 lifespan 完成数据库迁移、mod 加载等重 IO 操作。
    if stop_event.wait(_INITIAL_DELAY_SECONDS):
        return

    while not stop_event.is_set():
        try:
            _run_once(data_dir)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("backup scheduler iteration failed (non-fatal): %s", exc)

        # 等待下一轮（可被 stop_event 提前唤醒）
        if stop_event.wait(_POLL_INTERVAL_SECONDS):
            return


def _run_once(data_dir: str | os.PathLike[str] | None) -> None:
    """单轮：检查今天是否已备份，没有则备份；周日额外建 weekly；然后清理老旧备份。"""
    dirs = ensure_desktop_dirs(data_dir)
    backups_dir = dirs["backups"]

    if not _has_backup_today(backups_dir):
        version = os.environ.get("XCAGI_VERSION", "unknown")
        result = backup_database(data_dir, version=version)
        if result is not None:
            logger.info("scheduled backup created: %s", result.name)
            _sync_to_external(result)
            # 周日额外复制一份为 weekly 备份（保留 4 周，灾备硬约束）。
            if datetime.now().weekday() == 6:  # 0=Monday, 6=Sunday
                weekly = _make_weekly_copy(result)
                if weekly is not None:
                    _sync_to_external(weekly)
        else:
            logger.warning("scheduled backup failed (see migrate.backup_database logs)")

    _cleanup_old_backups(backups_dir, retention_days=_RETENTION_DAYS)


def _make_weekly_copy(daily_backup: Path) -> Path | None:
    """把周日的 daily 备份复制一份为 weekly 标记文件，保留 4 周。

    文件名格式：xcagi-{version}-weekly-{stamp}.db
    复制而非重新备份，避免对运行中的库再做一次 sqlite3.backup()。
    """
    match = _BACKUP_STAMP_RE.match(daily_backup.name)
    if match is None or _WEEKLY_MARKER in daily_backup.stem:
        return None
    stamp = match.group("stamp")
    weekly_name = daily_backup.name.replace(
        f"-{stamp}.db",
        f"-{_WEEKLY_MARKER}-{stamp}.db",
    )
    weekly_path = daily_backup.parent / weekly_name
    try:
        shutil.copy2(daily_backup, weekly_path)
        logger.info("weekly backup created: %s", weekly_path.name)
        return weekly_path
    except OSError as exc:
        logger.warning("failed to create weekly copy %s: %s", weekly_path, exc)
        return None


def _sync_to_external(backup_file: Path) -> None:
    """若配置了 XCAGI_EXTERNAL_BACKUP_DIR，把备份复制到外部目录（如 USB 盘）。

    外部目录不可用（USB 未插入）时仅记录 warning，不阻塞主流程。
    满足硬约束：备份须同时存于本地和外部，避免单点失效。
    """
    external = (os.environ.get("XCAGI_EXTERNAL_BACKUP_DIR") or "").strip()
    if not external:
        return
    target_dir = Path(external).expanduser()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, target_dir / backup_file.name)
        logger.info("backup synced to external: %s", target_dir / backup_file.name)
    except OSError as exc:
        # USB 未插入 / 权限不足 / 磁盘满 —— 仅警告，本地备份已成功
        logger.warning("external backup sync failed (non-fatal): %s", exc)


def _has_backup_today(backups_dir: Path) -> bool:
    """检查 backups/ 目录里是否有今天的定时备份。

    定时备份文件名格式：xcagi-{version}-{YYYYMMDDHHMMSS}.db
    只看文件名里的日期前缀（YYYYMMDD），不看 mtime（mtime 可能被复制操作改）。
    weekly 备份（含 weekly 标记）也算"今天的备份"，避免周日重复跑 daily。
    """
    today = datetime.now().strftime("%Y%m%d")
    for path in backups_dir.glob("xcagi-*.db"):
        match = _BACKUP_STAMP_RE.match(path.name)
        if match is not None and match.group("stamp").startswith(today):
            return True
    return False


def _cleanup_old_backups(backups_dir: Path, retention_days: int) -> None:
    """按时间和数量双重上限清理定时备份。

    - daily 备份（xcagi-{version}-{stamp}.db）：保留 retention_days 天
    - weekly 备份（xcagi-{version}-weekly-{stamp}.db）：保留 _RETENTION_WEEKLY_DAYS 天
    - 本地自动备份默认最多 2 份（最新恢复点 + weekly/recent fallback）
    - pending rollback 引用的数据库备份额外保护
    - *.bak（用户手动备份）：不动
    """
    cleanup_local_backups(
        backups_dir,
        retention_days=retention_days,
        weekly_retention_days=_RETENTION_WEEKLY_DAYS,
    )


def get_last_backup_info(data_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """返回最近一次备份信息，供 /api/desktop/status 暴露给前端/Electron。

    扫描 backups/xcagi-*.db 和 data/database_backups/*.bak，取 mtime 最新的。
    返回 {"path": str|None, "timestamp": iso|None, "size": int|None}。
    """
    dirs = ensure_desktop_dirs(data_dir)
    candidates: list[Path] = []
    backups_dir = dirs["backups"]
    if backups_dir.is_dir():
        candidates.extend(backups_dir.glob("xcagi-*.db"))
    legacy_dir = dirs["data"] / "database_backups"
    if legacy_dir.is_dir():
        candidates.extend(legacy_dir.glob("*.bak"))

    if not candidates:
        return {"path": None, "timestamp": None, "size": None}

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    return {
        "path": str(latest),
        "filename": latest.name,
        "timestamp": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "size": stat.st_size,
    }
