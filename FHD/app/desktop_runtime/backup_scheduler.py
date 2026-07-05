"""桌面端定时备份调度器。

桌面模式 + SQLite 下，FastAPI lifespan 启动一个 daemon 线程：
1. 启动后延迟几分钟（避开启动 IO 高峰）
2. 检查今天是否已有备份，没有则立即备份一次
3. 之后每 24 小时备份一次
4. 保留最近 N 天的备份，超出则清理老旧备份
5. 主进程退出时通过 Event 信号让线程优雅退出

不引入新依赖，仅用 threading。Celery/Redis 在桌面模式已禁用，不能依赖。
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .migrate import backup_database
from .paths import ensure_desktop_dirs, is_desktop_mode

logger = logging.getLogger(__name__)

# 启动后延迟备份的秒数（避开 lifespan 高峰，让 mod/索引先建完）。
_INITIAL_DELAY_SECONDS = 180
# 循环检查间隔。不到 24h 也可，但每次循环会判断"今天是否已备份"，
# 所以频繁检查不会导致频繁备份。
_POLL_INTERVAL_SECONDS = 3600
# 备份保留天数。超过则清理（按 mtime）。
_RETENTION_DAYS = 7

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
    """单轮：检查今天是否已备份，没有则备份；然后清理老旧备份。"""
    dirs = ensure_desktop_dirs(data_dir)
    backups_dir = dirs["backups"]

    if not _has_backup_today(backups_dir):
        version = os.environ.get("XCAGI_VERSION", "unknown")
        result = backup_database(data_dir, version=version)
        if result is not None:
            logger.info("scheduled backup created: %s", result.name)
        else:
            logger.warning("scheduled backup failed (see migrate.backup_database logs)")

    _cleanup_old_backups(backups_dir, retention_days=_RETENTION_DAYS)


def _has_backup_today(backups_dir: Path) -> bool:
    """检查 backups/ 目录里是否有今天的定时备份。

    定时备份文件名格式：xcagi-{version}-{YYYYMMDDHHMMSS}.db
    只看文件名里的日期前缀（YYYYMMDD），不看 mtime（mtime 可能被复制操作改）。
    """
    today = datetime.now().strftime("%Y%m%d")
    for path in backups_dir.glob("xcagi-*.db"):
        # 文件名格式 xcagi-{version}-{stamp}.db，stamp 是 %Y%m%d%H%M%S
        parts = path.stem.split("-")
        if len(parts) >= 3:
            stamp = parts[-1]
            if len(stamp) >= 8 and stamp[:8] == today:
                return True
    return False


def _cleanup_old_backups(backups_dir: Path, retention_days: int) -> None:
    """清理超过保留天数的定时备份。

    只清理 xcagi-*.db（定时备份产生的），不动 *.bak（用户手动备份产生的）。
    按 mtime 排序，保留最近 retention_days 天的。
    """
    if not backups_dir.is_dir():
        return

    cutoff = datetime.now() - timedelta(days=retention_days)
    cutoff_ts = cutoff.timestamp()

    for path in backups_dir.glob("xcagi-*.db"):
        try:
            if path.stat().st_mtime < cutoff_ts:
                path.unlink()
                logger.info("cleaned up old backup: %s", path.name)
        except OSError as exc:
            logger.warning("failed to clean up old backup %s: %s", path, exc)


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
