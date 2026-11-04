# mypy: disable-error-code="arg-type"
"""运行时真相：记录每次调度器 job 执行，回答「什么在跑 / 什么停了」。

这是文件 JSON 心跳永远做不到的单一真相源：心跳证明调度器*进程*活着，但单个
阶段可以静默停掉（生产 digest 冻结 12 天而心跳照跳）。每次阶段执行写一行到
``scheduler_job_runs``；``get_runtime_status`` 把它们按 job 汇总成
``last_run`` / ``last_success`` / ``state``，让停摆的 job 浮出来而非藏起来。

所有写入都是**失败安全**的：账本永远不能反过来把它在观测的 job 弄崩。
"""

from __future__ import annotations

import logging
import os
import re
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Iterator

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 一个日级 job 若在此窗口内没有成功过，视为 stale（默认 26h，给日任务留出抖动）。
DEFAULT_STALE_AFTER_SECONDS = int(
    os.environ.get("MODSTORE_JOB_STALE_AFTER_SECONDS", str(26 * 3600))
)

_DEFERRED_STATUS = "deferred"
_SAFE_EMPLOYEE_CRON_ERROR_CODE = re.compile(
    r"\b("
    r"employee_cron_(?:unsuccessful|execution_exception|policy_deferred):"
    r"[a-z0-9_]+(?::[a-z0-9_]+){0,2}"
    r"|employee_cron_input_resolution_failed"
    r")\b"
)
_SAFE_EXCEPTION_TYPES = frozenset(
    {
        "RuntimeError",
        "ValueError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "ImportError",
        "ModuleNotFoundError",
        "OSError",
        "FileNotFoundError",
        "PermissionError",
        "TimeoutError",
        "ConnectionError",
        "OperationalError",
        "IntegrityError",
    }
)
_SAFE_SCHEDULER_EXCEPTION = re.compile(r"^(" + "|".join(sorted(_SAFE_EXCEPTION_TYPES)) + r")\(")
_SAFE_PUBLIC_CODE = re.compile(r"^[a-z][a-z0-9_]*(?::[a-z0-9_]+){0,4}$")
_MAX_PUBLIC_CODE_LENGTH = 160
_MAX_SCAN_LIMIT = 5000
_REPLAY_ROW_LIMIT = 2000
_health_lock = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DeferredJobRun(Exception):
    """Record an expected policy hold without treating it as a job failure.

    The underlying operation keeps its own hold/veto evidence. This exception
    only tells the runtime ledger that a reviewed policy boundary, rather than
    an execution error, ended the scheduler run.
    """


def _as_utc(dt: datetime | None) -> datetime | None:
    """把可能是 naive（SQLite 回读）的时间戳统一成 aware-UTC，避免比较时炸。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def record_job_run(
    *,
    job_id: str,
    status: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    duration_ms: float = 0.0,
    error: str = "",
    node_id: str = "",
) -> None:
    """持久化一次 job 执行。失败安全：绝不向调用方抛异常。"""
    try:
        from modstore_server.db.scheduler_ops import JobRun
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            run = JobRun(
                job_id=job_id,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=float(duration_ms or 0.0),
                error=(error or "")[:4000],
                node_id=node_id or "",
            )
            session.add(run)
            session.flush()
            _upsert_job_health(session, run)
            _advance_checkpoint_if_contiguous(session, int(run.id))
            session.commit()
    except RECOVERABLE_ERRORS:  # pragma: no cover - 可观测性不能拖垮调度器
        logger.error("record_job_run 失败")


@contextmanager
def track_job_run(job_id: str, *, node_id: str = "") -> Iterator[None]:
    """包住一次 job 执行：退出时记录成功/失败/受控延迟 + 耗时。

    抛异常时记为 ``failed`` 并**原样重抛**——job 自身的错误处理不变，只是被观测。
    ``DeferredJobRun`` is the explicit exception: it is recorded as
    ``deferred`` and suppressed because the policy hold is expected.
    """
    started = _utcnow()
    status = "success"
    error = ""
    try:
        yield
    except DeferredJobRun as exc:
        status = _DEFERRED_STATUS
        error = str(exc)
    except RECOVERABLE_ERRORS as exc:
        status = "failed"
        error = repr(exc)
        raise
    finally:
        finished = _utcnow()
        record_job_run(
            job_id=job_id,
            status=status,
            started_at=started,
            finished_at=finished,
            duration_ms=(finished - started).total_seconds() * 1000.0,
            error=error,
            node_id=node_id,
        )


def record_skip(job_id: str, *, reason: str = "", node_id: str = "") -> None:
    """记录本节点跳过了某阶段（例如锁被另一节点持有）—— 不计为失败。"""
    now = _utcnow()
    record_job_run(
        job_id=job_id,
        status="skipped",
        started_at=now,
        finished_at=now,
        duration_ms=0.0,
        error=reason or "",
        node_id=node_id,
    )


def public_exception_type(exc: BaseException) -> str:
    """Return an allowlisted exception type, never a message or custom name."""
    name = type(exc).__name__
    return name if name in _SAFE_EXCEPTION_TYPES else "error"


def public_error_code(job_id: str, error: object) -> str | None:
    """Expose only reviewed scheduler codes, never raw exception text.

    The runtime endpoint is public. Scheduler errors can include provider or
    file-system details, so an error string is not a safe observability field.
    Employee cron wrappers deliberately raise a small allowlisted vocabulary.
    Any other job may expose only an allowlisted exception type, or a whole
    string that is already a lowercase code.
    """

    text = str(error or "").strip()
    if not text:
        return None
    if str(job_id or "").startswith("employee_cron"):
        match = _SAFE_EMPLOYEE_CRON_ERROR_CODE.search(text)
        if match:
            return match.group(1)[:_MAX_PUBLIC_CODE_LENGTH]
    exception = _SAFE_SCHEDULER_EXCEPTION.match(text)
    if exception:
        return f"scheduler_exception:{exception.group(1)}"
    if len(text) <= _MAX_PUBLIC_CODE_LENGTH and _SAFE_PUBLIC_CODE.fullmatch(text):
        return text
    return None


def _job_summary(
    job_id: str, runs: list[Any], *, now: datetime, stale_after: int
) -> dict[str, Any]:
    """Project an in-memory run list. Ledger reads use ``scheduler_job_health``."""
    runs_sorted = sorted(runs, key=lambda run: run.id)
    last = runs_sorted[-1]
    last_success = next((run for run in reversed(runs_sorted) if run.status == "success"), None)
    consecutive_failures = 0
    for run in reversed(runs_sorted):
        if run.status == "failed":
            consecutive_failures += 1
        elif run.status in {"success", _DEFERRED_STATUS}:
            break
    last_success_at = _as_utc(last_success.started_at) if last_success else None
    age = (now - last_success_at).total_seconds() if last_success_at else None
    if last.status == _DEFERRED_STATUS:
        state = _DEFERRED_STATUS
    elif last.status == "failed":
        state = "failing"
    elif last_success_at is None or (age is not None and age > stale_after):
        state = "stale"
    else:
        state = "healthy"
    last_run_at = _as_utc(last.started_at)
    return {
        "job_id": job_id,
        "state": state,
        "last_status": last.status,
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "seconds_since_success": round(age) if age is not None else None,
        "consecutive_failures": consecutive_failures,
        "runs_counted": len(runs_sorted),
        "last_error_code": public_error_code(job_id, getattr(last, "error", "")),
    }


def _health_insert(session: Any) -> Any:
    name = session.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def _upsert_job_health(session: Any, run: Any) -> None:
    """Apply one ledger row to its summary. Older ids never increment the row."""
    from sqlalchemy import case

    from modstore_server.db.scheduler_ops import JobHealth

    table = JobHealth.__table__
    status = str(run.status or "")
    code = (public_error_code(str(run.job_id), run.error) or "")[:_MAX_PUBLIC_CODE_LENGTH]
    stmt = _health_insert(session)(table).values(
        job_id=str(run.job_id),
        last_run_id=int(run.id),
        last_status=status[:16],
        last_started_at=run.started_at,
        last_success_started_at=run.started_at if status == "success" else None,
        consecutive_failures=1 if status == "failed" else 0,
        total_runs=1,
        runs_since_success=0 if status == "success" else 1,
        last_error_code=code,
    )
    excluded = stmt.excluded
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["job_id"],
            set_={
                "last_run_id": excluded.last_run_id,
                "last_status": excluded.last_status,
                "last_started_at": excluded.last_started_at,
                "last_error_code": excluded.last_error_code,
                "total_runs": table.c.total_runs + 1,
                "consecutive_failures": case(
                    (excluded.last_status == "success", 0),
                    (excluded.last_status == _DEFERRED_STATUS, 0),
                    (excluded.last_status == "failed", table.c.consecutive_failures + 1),
                    else_=table.c.consecutive_failures,
                ),
                "runs_since_success": case(
                    (excluded.last_status == "success", 0),
                    else_=table.c.runs_since_success + 1,
                ),
                "last_success_started_at": case(
                    (excluded.last_status == "success", excluded.last_started_at),
                    else_=table.c.last_success_started_at,
                ),
            },
            where=excluded.last_run_id > table.c.last_run_id,
        )
    )


def _advance_checkpoint_if_contiguous(session: Any, run_id: int) -> None:
    from sqlalchemy import update

    from modstore_server.db.scheduler_ops import SchedulerHealthCheckpoint

    table = SchedulerHealthCheckpoint.__table__
    session.execute(
        update(table)
        .where(table.c.singleton == 1, table.c.summarized_through_id == run_id - 1)
        .values(summarized_through_id=run_id)
    )


def _set_checkpoint(session: Any, through: int) -> None:
    from sqlalchemy import update

    from modstore_server.db.scheduler_ops import SchedulerHealthCheckpoint

    table = SchedulerHealthCheckpoint.__table__
    updated = session.execute(
        update(table)
        .where(table.c.singleton == 1, table.c.summarized_through_id < through)
        .values(summarized_through_id=through)
    )
    if updated.rowcount is not None and updated.rowcount > 0:
        return
    exists = session.query(SchedulerHealthCheckpoint.singleton).filter_by(singleton=1).first()
    if exists is None:
        session.add(SchedulerHealthCheckpoint(singleton=1, summarized_through_id=through))


def _rows_by_ids(session: Any, ids: list[int], *, with_error: bool) -> dict[int, Any]:
    from modstore_server.db.scheduler_ops import JobRun

    found: dict[int, Any] = {}
    columns = [JobRun.id, JobRun.started_at]
    if with_error:
        columns.extend([JobRun.status, JobRun.error])
    for offset in range(0, len(ids), 500):
        chunk = ids[offset : offset + 500]
        for row in session.query(*columns).filter(JobRun.id.in_(chunk)).all():
            found[int(row.id)] = row
    return found


def _rebuild_job_health(session: Any) -> None:
    """Replace the summary from indexed aggregates. This does not rank the ledger."""
    from sqlalchemy import func

    from modstore_server.db.scheduler_ops import JobHealth, JobRun

    snapshot_max = int(session.query(func.max(JobRun.id)).scalar() or 0)
    session.query(JobHealth).delete(synchronize_session=False)
    if snapshot_max == 0:
        _set_checkpoint(session, 0)
        return
    totals = (
        session.query(JobRun.job_id, func.max(JobRun.id), func.count(JobRun.id))
        .group_by(JobRun.job_id)
        .all()
    )
    success_ids = dict(
        session.query(JobRun.job_id, func.max(JobRun.id))
        .filter(JobRun.status == "success")
        .group_by(JobRun.job_id)
        .all()
    )
    breaker_ids = dict(
        session.query(JobRun.job_id, func.max(JobRun.id))
        .filter(JobRun.status.in_(("success", _DEFERRED_STATUS)))
        .group_by(JobRun.job_id)
        .all()
    )
    breaker_sub = (
        session.query(JobRun.job_id.label("job_id"), func.max(JobRun.id).label("breaker_id"))
        .filter(JobRun.status.in_(("success", _DEFERRED_STATUS)))
        .group_by(JobRun.job_id)
        .subquery()
    )
    fail_since = dict(
        session.query(JobRun.job_id, func.count(JobRun.id))
        .join(breaker_sub, breaker_sub.c.job_id == JobRun.job_id)
        .filter(JobRun.status == "failed", JobRun.id > breaker_sub.c.breaker_id)
        .group_by(JobRun.job_id)
        .all()
    )
    all_failed = dict(
        session.query(JobRun.job_id, func.count(JobRun.id))
        .filter(JobRun.status == "failed")
        .group_by(JobRun.job_id)
        .all()
    )
    success_sub = (
        session.query(JobRun.job_id.label("job_id"), func.max(JobRun.id).label("success_id"))
        .filter(JobRun.status == "success")
        .group_by(JobRun.job_id)
        .subquery()
    )
    since_success = dict(
        session.query(JobRun.job_id, func.count(JobRun.id))
        .join(success_sub, success_sub.c.job_id == JobRun.job_id)
        .filter(JobRun.id > success_sub.c.success_id)
        .group_by(JobRun.job_id)
        .all()
    )
    last_ids = [int(last_id) for _, last_id, _ in totals]
    success_only = [int(value) for value in success_ids.values() if int(value) not in set(last_ids)]
    last_rows = _rows_by_ids(session, last_ids, with_error=True)
    success_rows = _rows_by_ids(session, success_only, with_error=False)
    for job_id, last_id, total in totals:
        last = last_rows[int(last_id)]
        success_id = success_ids.get(job_id)
        if job_id in breaker_ids:
            failures = int(fail_since.get(job_id) or 0)
        else:
            failures = int(all_failed.get(job_id) or 0)
        if success_id is None:
            success_at = None
            since = int(total)
        else:
            success = last_rows.get(int(success_id)) or success_rows[int(success_id)]
            success_at = success.started_at
            since = int(since_success.get(job_id) or 0)
        session.add(
            JobHealth(
                job_id=str(job_id),
                last_run_id=int(last_id),
                last_status=str(last.status or "")[:16],
                last_started_at=last.started_at,
                last_success_started_at=success_at,
                consecutive_failures=failures,
                total_runs=int(total),
                runs_since_success=since,
                last_error_code=(public_error_code(str(job_id), last.error) or "")[
                    :_MAX_PUBLIC_CODE_LENGTH
                ],
            )
        )
    _set_checkpoint(session, snapshot_max)


def _replay_tail(session: Any, through: int, snapshot_max: int) -> bool:
    from modstore_server.db.scheduler_ops import JobRun

    rows = (
        session.query(JobRun)
        .filter(JobRun.id > through, JobRun.id <= snapshot_max)
        .order_by(JobRun.id.asc())
        .limit(_REPLAY_ROW_LIMIT + 1)
        .all()
    )
    if len(rows) > _REPLAY_ROW_LIMIT:
        return False
    for run in rows:
        _upsert_job_health(session, run)
    _set_checkpoint(session, snapshot_max)
    return True


def _ensure_job_health(session: Any) -> None:
    from sqlalchemy import func

    from modstore_server.db.scheduler_ops import JobRun, SchedulerHealthCheckpoint

    with _health_lock:
        snapshot_max = int(session.query(func.max(JobRun.id)).scalar() or 0)
        checkpoint = session.get(SchedulerHealthCheckpoint, 1)
        through = int(checkpoint.summarized_through_id) if checkpoint is not None else 0
        if checkpoint is not None and through >= snapshot_max:
            return
        if (
            checkpoint is not None
            and snapshot_max - through <= _REPLAY_ROW_LIMIT
            and _replay_tail(session, through, snapshot_max)
        ):
            session.commit()
            return
        _rebuild_job_health(session)
        session.commit()


def _summary_from_health(
    row: Any, *, now: datetime, stale_after: int, scan_limit: int
) -> dict[str, Any]:
    last_status = str(row.last_status or "")
    last_run_at = _as_utc(row.last_started_at)
    last_success_at = _as_utc(row.last_success_started_at)
    age = (now - last_success_at).total_seconds() if last_success_at else None
    if last_status == _DEFERRED_STATUS:
        state = _DEFERRED_STATUS
    elif last_status == "failed":
        state = "failing"
    elif last_success_at is None or (age is not None and age > stale_after):
        state = "stale"
    else:
        state = "healthy"
    total = int(row.total_runs or 0)
    since = int(row.runs_since_success or 0)
    outside = last_success_at is not None and since >= scan_limit
    code = str(row.last_error_code or "") or None
    return {
        "job_id": row.job_id,
        "state": state,
        "last_status": last_status,
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "seconds_since_success": round(age) if age is not None else None,
        "consecutive_failures": min(int(row.consecutive_failures or 0), scan_limit),
        "runs_counted": min(total, scan_limit) + (1 if outside else 0),
        "last_error_code": code,
    }


def get_runtime_status(
    *, stale_after_seconds: int | None = None, scan_limit: int = 5000
) -> dict[str, Any]:
    """把按 job 保存的汇总读成运行时真相。

    返回 ``{"generated_at", "stale_after_seconds", "jobs": [...], "summary": {...}, "ok"}``。
    读取不按整本账本做窗口排序。``scan_limit`` 只限制对外的计数，并始终保留每个
    job 的最后一次成功，因此高频任务不能挤掉日任务。
    """
    stale_after = int(
        stale_after_seconds if stale_after_seconds is not None else DEFAULT_STALE_AFTER_SECONDS
    )
    bounded_scan = max(1, min(int(scan_limit), _MAX_SCAN_LIMIT))
    now = _utcnow()

    try:
        from modstore_server.db.scheduler_ops import JobHealth
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            _ensure_job_health(session)
            rows = session.query(JobHealth).order_by(JobHealth.job_id).all()
    except RECOVERABLE_ERRORS as exc:
        logger.error("get_runtime_status 读取失败: error_type=%s", public_exception_type(exc))
        return {
            "generated_at": now.isoformat(),
            "stale_after_seconds": stale_after,
            "jobs": [],
            "summary": {"error": "runtime_status_unavailable"},
            "ok": False,
        }

    jobs = [
        _summary_from_health(row, now=now, stale_after=stale_after, scan_limit=bounded_scan)
        for row in rows
    ]
    summary = {
        "total": len(jobs),
        "healthy": sum(1 for job in jobs if job["state"] == "healthy"),
        "failing": sum(1 for job in jobs if job["state"] == "failing"),
        "stale": sum(1 for job in jobs if job["state"] == "stale"),
        "deferred": sum(1 for job in jobs if job["state"] == _DEFERRED_STATUS),
    }
    return {
        "generated_at": now.isoformat(),
        "stale_after_seconds": stale_after,
        "jobs": jobs,
        "summary": summary,
        "ok": True,
    }


__all__ = [
    "DEFAULT_STALE_AFTER_SECONDS",
    "DeferredJobRun",
    "get_runtime_status",
    "public_error_code",
    "public_exception_type",
    "record_job_run",
    "record_skip",
    "track_job_run",
]
