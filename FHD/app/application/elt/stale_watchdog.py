"""回收长时间没有进展的 ELT 运行，避免僵尸任务占满线程池饿死后续导入。"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import column, func, table, update

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 30.0
_STARTED_LOCK = threading.Lock()
_STARTED = False
_BATCH_KINDS = ("batch_execute", "batch_rollback")
_ACTIVE_STATUSES = ("previewing", "executing")
_RUNS: Any = table(
    "elt_runs",
    column("status"),
    column("stage"),
    column("error_code"),
    column("error_message"),
    column("operation_kind"),
    column("operation_token"),
    column("operation_lease_until"),
    column("updated_at"),
    column("target_type"),
)


def stale_after_seconds() -> float:
    raw = str(os.environ.get("ELT_STALE_SECONDS") or "900").strip()
    try:
        return max(120.0, float(raw))
    except ValueError:
        return 900.0


def _cutoff(seconds: float) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=seconds)


def _release(values: dict[str, Any]) -> dict[str, Any]:
    return {
        **values,
        "operation_kind": None,
        "operation_token": None,
        "operation_lease_until": None,
        "updated_at": func.current_timestamp(),
    }


def sweep_stale_runs() -> int:
    """把长时间无更新的进行态运行标为可重试，并释放租约。"""
    from app.db import get_engine

    engine = get_engine()
    cutoff = _cutoff(stale_after_seconds())
    external_batch = _RUNS.c.operation_kind.in_(_BATCH_KINDS) & (_RUNS.c.target_type != "abnormal")
    active = _RUNS.c.status.in_(_ACTIVE_STATUSES) & (_RUNS.c.updated_at <= cutoff)
    try:
        with engine.begin() as connection:
            unknown = connection.execute(
                update(_RUNS)
                .where(active, external_batch)
                .values(
                    **_release(
                        {
                            "status": "outcome_unknown",
                            "stage": "outcome_unknown",
                            "error_code": "ELT_OUTCOME_UNKNOWN",
                            "error_message": "外部批处理长时间无进展，结果无法确认，请核对后人工处理",
                        }
                    )
                )
            )
            interrupted = connection.execute(
                update(_RUNS)
                .where(active, ~external_batch)
                .values(
                    **_release(
                        {
                            "status": "interrupted",
                            "stage": "interrupted",
                            "error_code": "ELT_EXECUTION_INTERRUPTED",
                            "error_message": "长时间没有进展，已停止等待；未写入业务数据，请重新导入",
                        }
                    )
                )
            )
            total = int(unknown.rowcount or 0) + int(interrupted.rowcount or 0)
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
