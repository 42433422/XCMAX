"""标记租约已失效的 ELT 运行；数据库状态回收不会终止工作线程。"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import Table, case, exists, func, or_, select, update

from app.db.models.elt import EltRun, EltRunRow
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 30.0
_STARTED_LOCK = threading.Lock()
_STOP_EVENT: threading.Event | None = None
_THREAD: threading.Thread | None = None
_RUNS = cast("Table", EltRun.__table__)
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


def lease_grace_seconds() -> float:
    """租约到期后再给执行线程的宽限；之后仍零进度即可安全回收。"""
    raw = str(os.environ.get("ELT_LEASE_GRACE_SECONDS") or "120").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 120.0


def sweep_stale_runs() -> int:
    """仅回收已失效租约；未知批次保留令牌和回执供核对。"""
    from app.db import get_engine

    runs = _RUNS.c
    rows = cast("Table", EltRunRow.__table__).c
    batch = runs.operation_kind.in_(("batch_execute", "batch_rollback"))
    no_write = (
        (runs.target_type == "abnormal")
        & (runs.operation_kind == "batch_execute")
        & runs.operation_token.is_not(None)
        & (runs.executed_rows == 0)
        & (runs.receipt_json == "{}")
        & ~exists(
            select(1).where(
                rows.run_id == runs.id,
                or_(
                    rows.execution_status.is_not(None),
                    rows.after_json.is_(None),
                    rows.after_json != "{}",
                ),
            )
        )
    )
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=stale_after_seconds())
    lease_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=lease_grace_seconds())
    # 已拿租约但一行都没写：没有外部副作用可核对，不必等满 900 秒，
    # 租约过期加宽限后即可安全判中断，避免占着执行槽位饿死后续导入。
    claimed_without_progress = (
        runs.operation_token.is_not(None)
        & runs.operation_lease_until.is_not(None)
        & (runs.operation_lease_until <= lease_cutoff)
        & (runs.executed_rows == 0)
        & (runs.progress == 0)
        & (runs.receipt_json == "{}")
    )
    active = (
        or_(
            runs.status.in_(("previewing", "executing")), batch & (runs.status != "outcome_unknown")
        )
        & or_((runs.updated_at <= cutoff), claimed_without_progress)
        & or_(
            runs.operation_token.is_(None), runs.operation_lease_until <= func.current_timestamp()
        )
    )
    sweeps = (
        (
            claimed_without_progress & ~batch,
            "interrupted",
            "ELT_EXECUTION_INTERRUPTED",
            "执行已中断，未写入业务数据，请重新导入",
            _RELEASED,
        ),
        (
            no_write,
            "interrupted",
            "ELT_EXECUTION_INTERRUPTED",
            "执行已中断，未写入业务数据，请重新导入",
            _RELEASED,
        ),
        (
            batch,
            "outcome_unknown",
            "ELT_OUTCOME_UNKNOWN",
            "批处理长时间无进展，结果无法确认，请核对后人工处理",
            {
                "updated_at": func.current_timestamp(),
                "rollback_status": case(
                    (runs.operation_kind == "batch_rollback", "outcome_unknown"),
                    else_=runs.rollback_status,
                ),
            },
        ),
        (
            or_(~batch, runs.operation_kind.is_(None)),
            "interrupted",
            "ELT_EXECUTION_INTERRUPTED",
            "长时间没有进展，请核对实际结果后重试",
            _RELEASED,
        ),
    )
    total = 0
    try:
        with get_engine().begin() as connection:
            for where, status, code, message, values in sweeps:
                result = connection.execute(
                    update(_RUNS)
                    .where(active, where)
                    .values(
                        status=status,
                        stage=status,
                        error_code=code,
                        error_message=message,
                        **values,
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
    global _STOP_EVENT, _THREAD
    with _STARTED_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        stop_event = threading.Event()

        def loop() -> None:
            while not stop_event.is_set():
                try:
                    sweep_stale_runs()
                except RECOVERABLE_ERRORS:
                    logger.debug("ELT 看门狗单次扫描失败", exc_info=True)
                if stop_event.wait(_INTERVAL_SECONDS):
                    break

        _STOP_EVENT = stop_event
        _THREAD = threading.Thread(target=loop, name="elt-stale-watchdog", daemon=True)
        _THREAD.start()
        return True


def stop_stale_watchdog() -> None:
    """停止后续扫描；尚未退出的线程继续占有唯一槽位，避免重复启动。"""
    with _STARTED_LOCK:
        if _STOP_EVENT is not None:
            _STOP_EVENT.set()
        thread = _THREAD
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=5.0)
