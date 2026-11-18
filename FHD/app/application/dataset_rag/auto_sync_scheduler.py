"""知识库来源定时同步：进程内 daemon 线程，按新鲜度阈值批量刷新。

桌面/服务端都没有部署 celery beat，因此用 threading 提供一个可关闭的
轻量调度循环（与桌面备份调度器一致）。默认关闭，仅当
``XCAGI_KB_AUTO_REFRESH_HOURS>0`` 时启动；每轮只刷新超过该时长未同步的
来源，未变化的页面不会产生新版本。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

INITIAL_DELAY_SECONDS = 120
_lag_lock = threading.Lock()
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def auto_refresh_interval_hours() -> float:
    """读取 ``XCAGI_KB_AUTO_REFRESH_HOURS``；缺省/非法/非正数表示关闭。"""
    raw = os.environ.get("XCAGI_KB_AUTO_REFRESH_HOURS", "").strip()
    if not raw:
        return 0.0
    try:
        hours = float(raw)
    except ValueError:
        return 0.0
    return hours if hours > 0 else 0.0


def run_due_source_sync_once(*, interval_hours: float | None = None) -> dict[str, Any]:
    """执行一轮到期来源同步；异常不外抛，避免后台线程退出。"""
    hours = interval_hours if interval_hours is not None else auto_refresh_interval_hours()
    if hours <= 0:
        return {"skipped": True, "reason": "disabled"}
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    try:
        return get_dataset_rag_app_service().refresh_all_due_sources(max_age_hours=hours)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("知识库来源定时同步失败: %s", exc)
        return {"success": False, "error": str(exc)}


def _scheduler_loop(stop_event: threading.Event) -> None:
    interval = auto_refresh_interval_hours()
    if interval <= 0:
        return
    if stop_event.wait(INITIAL_DELAY_SECONDS):
        return
    interval_seconds = max(300.0, interval * 3600.0)
    while not stop_event.is_set():
        outcome = run_due_source_sync_once(interval_hours=interval)
        logger.info(
            "知识库来源定时同步：datasets=%s processed=%s changed=%s failed=%s fresh=%s",
            outcome.get("datasets"),
            outcome.get("processed"),
            outcome.get("changed"),
            outcome.get("failed"),
            outcome.get("fresh"),
        )
        if stop_event.wait(interval_seconds):
            break


def start_auto_sync_scheduler() -> bool:
    """启动定时同步线程（幂等）；返回是否已运行。"""
    global _stop_event, _thread
    if auto_refresh_interval_hours() <= 0:
        return False
    with _lag_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop_event = threading.Event()
        _thread = threading.Thread(
            target=_scheduler_loop,
            args=(_stop_event,),
            name="xcagi-kb-auto-sync",
            daemon=True,
        )
        _thread.start()
        return True


def stop_auto_sync_scheduler() -> None:
    """停止定时同步线程（幂等）。"""
    global _stop_event, _thread
    with _lag_lock:
        if _stop_event is not None:
            _stop_event.set()
        _stop_event = None
        _thread = None
