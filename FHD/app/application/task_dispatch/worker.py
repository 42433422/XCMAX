"""派工后台 worker：抽干 pending 工单，让派工脱离请求线程。

- 事件驱动：``handle_chat_dispatch`` 入队后 ``notify`` 唤醒，立即执行（低延迟）。
- 轮询兜底：周期性扫 ``list_pending``，捡起进程重启前遗留 / 漏唤醒的工单（重启安全）。
- 守护线程，``daemon=True``；FHD web 启动时由 lifespan 自启，可用环境变量
  ``FHD_DISABLE_WORK_ORDER_WORKER=1`` 关闭。

执行委托给 :meth:`TaskDispatchService.execute_work_order`（含异常重试、状态机、
结果落库、tier-2 回流交流圈）。worker 只负责"何时抽干"。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 8.0
_DRAIN_BATCH = 20


class WorkOrderWorker:
    def __init__(
        self, *, service: Any = None, poll_interval: float = _DEFAULT_POLL_INTERVAL
    ) -> None:
        self._service = service
        self._poll_interval = poll_interval
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _svc(self) -> Any:
        if self._service is None:
            from app.application.task_dispatch.service import get_task_dispatch_service

            self._service = get_task_dispatch_service()
        return self._service

    def start(self) -> dict[str, Any]:
        if os.environ.get("FHD_DISABLE_WORK_ORDER_WORKER", "").strip() in {"1", "true", "True"}:
            return {"running": False, "reason": "disabled_by_env"}
        if self._thread is not None and self._thread.is_alive():
            return {"running": True, "reason": "already_running"}
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="work-order-worker", daemon=True)
        self._thread.start()
        return {"running": True}

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        # 启动即抽一次，捡回重启前遗留的 pending。
        while not self._stop.is_set():
            try:
                drained = self.drain_once()
            except RECOVERABLE_ERRORS:
                logger.warning("work-order worker drain 异常", exc_info=True)
                drained = 0
            if drained == 0:
                self._wake.wait(timeout=self._poll_interval)
                self._wake.clear()

    def drain_once(self) -> int:
        svc = self._svc()
        pending = svc.list_pending(limit=_DRAIN_BATCH)
        count = 0
        for record in pending:
            if self._stop.is_set():
                break
            try:
                svc.execute_work_order(record["work_order_id"])
                count += 1
            except RECOVERABLE_ERRORS:
                logger.warning(
                    "work-order 执行异常 work_order=%s", record.get("work_order_id"), exc_info=True
                )
        return count


_worker: WorkOrderWorker | None = None


def get_work_order_worker() -> WorkOrderWorker:
    global _worker
    if _worker is None:
        _worker = WorkOrderWorker()
    return _worker


def start_work_order_worker() -> dict[str, Any]:
    return get_work_order_worker().start()


def stop_work_order_worker() -> None:
    if _worker is not None:
        _worker.stop()


def notify_work_order_worker() -> None:
    if _worker is not None:
        _worker.notify()


__all__ = [
    "WorkOrderWorker",
    "get_work_order_worker",
    "start_work_order_worker",
    "stop_work_order_worker",
    "notify_work_order_worker",
]
