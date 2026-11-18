"""回收长时间没有进展的 ELT 运行，避免僵尸任务占满线程池饿死后续导入。"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, update

from app.db.models.elt import EltRun
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 30.0
_STARTED_LOCK = threading.Lock()
_STARTED = False
_RUNS = EltRun.__table__
_RELEASED = {
    "operation_kind": None,
    "operation_token": None,
    "operation_lease_until": None,
    "updated_at": func.current_timestamp(),
}


def stale_after_seconds() -> float:
    raw = str(os.environ.get("ELT_STALE_SECONDS") or "900").strip()
    try:
        return max(120.0, float(raw))
    except ValueError:
        return 900.0


def sweep_stale_runs() -> int:
    """把长时间无更新的进行态运行标为可重试，并释放租约。"""
    from app.db import get_engine

    runs = _RUNS.c
    external = runs.operation_kind.in_(("batch_execute", "batch_rollback")) & (
        runs.target_type != "abnormal"
    )
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=stale_after_seconds())
    active = runs.status.in_(("previewing", "executing")) & (runs.updated_at <= cutoff)
    sweeps = (
        (
            external,
            "outcome_unknown",
            "ELT_OUTCOME_UNKNOWN",
            "外部批处理长时间无进展，结果无法确认，请核对后人工处理",
        ),
        (
            ~external,
            "interrupted",
            "ELT_EXECUTION_INTERRUPTED",
            "长时间没有进展，已停止等待；未写入业务数据，请重新导入",
        ),
    )
    total = 0
    try:
        with get_engine().begin() as connection:
            for where, status, code, message in sweeps:
                result = connection.execute(
                    update(_RUNS)
                    .where(active, where)
                    .values(
                        status=status,
                        stage=status,
                        error_code=code,
                        error_message=message,
                        **_RELEASED,
                    )
                )
                total += int(result.rowcount or 0)
    except RECOVERABLE_ERRORS:
        logger.exception("ELT 无进展运行回收失败")
        return 0
    if total:
        logger.warning("ELT 无进展运行已回收：%s 个", total)
    return total


def start_stale_watchdog() -> bool:
    """幂等启动后台看门狗；返回本次是否新建了线程。"""
    global _STARTED
    with _STARTED_LOCK:
        if _STARTED:
            return False
        _STARTED = True

    def loop() -> None:
        while True:
            try:
                sweep_stale_runs()
            except RECOVERABLE_ERRORS:
                logger.debug("ELT 看门狗单次扫描失败", exc_info=True)
            time.sleep(_INTERVAL_SECONDS)

    threading.Thread(target=loop, name="elt-stale-watchdog", daemon=True).start()
    return True
