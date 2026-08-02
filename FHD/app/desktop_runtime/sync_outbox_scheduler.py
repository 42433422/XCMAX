"""XCmax 同步 outbox 补推调度器。

企业端写交付进度 / 权益变更时 ``record_change`` 只入本地 outbox；
路由里的即时 push 是 best-effort，断网或失败后没有人再推，进度会
滞留客户桌面。此调度器在后台周期检查 pending outbox，有积压才补推
（无积压不碰网络），保证离线期间的进度最终到达管理端。

与 ``backup_scheduler`` 同范式：不引入新依赖，仅用 threading；
``XCMAX_SYNC_AUTO_PUSH=0`` 可整体关闭。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 启动延迟：避开 lifespan 数据库迁移 / Mod 装载高峰。
_INITIAL_DELAY_SECONDS = 20
_DEFAULT_INTERVAL_SECONDS = 120
_MIN_INTERVAL_SECONDS = 30

_lock = threading.Lock()
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def _enabled() -> bool:
    raw = (os.environ.get("XCMAX_SYNC_AUTO_PUSH") or "1").strip().lower()
    return raw not in {"0", "false", "off"}


def _interval_seconds() -> int:
    raw = os.environ.get("XCMAX_SYNC_PUSH_INTERVAL_SECONDS", "")
    try:
        return max(_MIN_INTERVAL_SECONDS, int(raw))
    except ValueError:
        return _DEFAULT_INTERVAL_SECONDS


def start_sync_outbox_scheduler() -> None:
    """幂等启动补推线程；测试进程与 ``XCMAX_SYNC_AUTO_PUSH=0`` 下不启动。"""
    global _stop_event, _thread

    if not _enabled() or "PYTEST_CURRENT_TEST" in os.environ:
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event = threading.Event()
        _thread = threading.Thread(
            target=_scheduler_loop,
            args=(_stop_event,),
            name="xcmax-sync-outbox",
            daemon=True,
        )
        _thread.start()
        logger.info("xcmax sync outbox scheduler started (interval=%ss)", _interval_seconds())


def stop_sync_outbox_scheduler(timeout: float = 5.0) -> None:
    """通知补推线程退出并等待。FastAPI shutdown 时调用。"""
    global _stop_event, _thread

    with _lock:
        if _stop_event is None or _thread is None:
            return
        _stop_event.set()
        _thread.join(timeout=timeout)
        _stop_event = None
        _thread = None
        logger.info("xcmax sync outbox scheduler stopped")


def _scheduler_loop(stop_event: threading.Event) -> None:
    if stop_event.wait(_INITIAL_DELAY_SECONDS):
        return
    while not stop_event.is_set():
        try:
            push_pending_outbox_once()
        except RECOVERABLE_ERRORS as exc:
            logger.warning("sync outbox auto push failed (non-fatal): %s", exc)
        if stop_event.wait(_interval_seconds()):
            return


def push_pending_outbox_once() -> dict[str, Any]:
    """有积压才推送；无积压直接返回，不碰网络。"""
    from app.db.xcmax_sync import SyncDb

    if not SyncDb().get_pending_outbox(limit=1):
        return {"sent": 0, "failed": 0, "total_pending": 0}

    from app.application.xcmax_sync_app import push_outbox

    result = push_outbox(
        remote_host=os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147"),
        remote_port=int(os.environ.get("XCMAX_REMOTE_PORT", "9999")),
    )
    logger.info("sync outbox auto push: %s", result)
    return dict(result) if isinstance(result, dict) else {"result": result}
