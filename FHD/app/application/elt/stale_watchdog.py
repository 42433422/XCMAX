"""回收长时间没有进展的 ELT 运行，避免僵尸任务占满线程池饿死后续导入。"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 30.0
_STARTED_LOCK = threading.Lock()
_STARTED = False


def stale_after_seconds() -> float:
    raw = str(os.environ.get("ELT_STALE_SECONDS") or "900").strip()
    try:
        return max(120.0, float(raw))
    except ValueError:
        return 900.0


def _cutoff_text(seconds: float) -> str:
    return (datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def sweep_stale_runs() -> int:
    """把长时间无更新的进行态运行标为可重试，并释放租约。"""
    from sqlalchemy import text

    from app.db import get_engine

    engine = get_engine()
    cutoff = _cutoff_text(stale_after_seconds())
    sqlite = engine.dialect.name == "sqlite"
    stale_condition = (
        "datetime(updated_at) <= datetime(:cutoff)" if sqlite else "updated_at <= :cutoff"
    )
    released = (
        "operation_kind = NULL, operation_token = NULL, operation_lease_until = NULL,"
    )
    try:
        with engine.begin() as connection:
            unknown = connection.execute(
                text(
                    f"""
                    UPDATE elt_runs
                    SET status = 'outcome_unknown', stage = 'outcome_unknown',
                        error_code = 'ELT_OUTCOME_UNKNOWN',
                        error_message = '外部批处理长时间无进展，结果无法确认，请核对后人工处理',
                        {released}
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status IN ('previewing', 'executing')
                      AND operation_kind IN ('batch_execute', 'batch_rollback')
                      AND target_type != 'abnormal'
                      AND {stale_condition}
                    """
                ),
                {"cutoff": cutoff},
            )
            interrupted = connection.execute(
                text(
                    f"""
                    UPDATE elt_runs
                    SET status = 'interrupted', stage = 'interrupted',
                        error_code = 'ELT_EXECUTION_INTERRUPTED',
                        error_message = '长时间没有进展，已停止等待；未写入业务数据，请重新导入',
                        {released}
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status IN ('previewing', 'executing')
                      AND NOT (operation_kind IN ('batch_execute', 'batch_rollback')
                               AND target_type != 'abnormal')
                      AND {stale_condition}
                    """
                ),
                {"cutoff": cutoff},
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
