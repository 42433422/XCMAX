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
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# 一个日级 job 若在此窗口内没有成功过，视为 stale（默认 26h，给日任务留出抖动）。
DEFAULT_STALE_AFTER_SECONDS = int(
    os.environ.get("MODSTORE_JOB_STALE_AFTER_SECONDS", str(26 * 3600))
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    """把可能是 naive（SQLite 回读）的时间戳统一成 aware-UTC，避免比较时炸。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


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
            session.add(
                JobRun(
                    job_id=job_id,
                    status=status,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=float(duration_ms or 0.0),
                    error=(error or "")[:4000],
                    node_id=node_id or "",
                )
            )
            session.commit()
    except Exception:  # pragma: no cover - 可观测性不能拖垮调度器
        logger.exception("record_job_run 失败: job_id=%s status=%s", job_id, status)


@contextmanager
def track_job_run(job_id: str, *, node_id: str = "") -> Iterator[None]:
    """包住一次 job 执行：退出时记录成功/失败 + 耗时。

    抛异常时记为 ``failed`` 并**原样重抛**——job 自身的错误处理不变，只是被观测。
    """
    started = _utcnow()
    status = "success"
    error = ""
    try:
        yield
    except Exception as exc:
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


def _job_summary(
    job_id: str, runs: list[Any], *, now: datetime, stale_after: int
) -> dict[str, Any]:
    runs_sorted = sorted(runs, key=lambda r: r.id)
    last = runs_sorted[-1]
    last_success = next(
        (r for r in reversed(runs_sorted) if r.status == "success"), None
    )

    consecutive_failures = 0
    for r in reversed(runs_sorted):
        if r.status == "failed":
            consecutive_failures += 1
        elif r.status == "success":
            break

    last_success_at = _as_utc(last_success.started_at) if last_success else None
    age = (now - last_success_at).total_seconds() if last_success_at else None

    if last.status == "failed":
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
    }


def get_runtime_status(
    *, stale_after_seconds: int | None = None, scan_limit: int = 5000
) -> dict[str, Any]:
    """把账本汇总成按 job 的运行时真相。

    返回 ``{"generated_at", "stale_after_seconds", "jobs": [...], "summary": {...}, "ok"}``，
    每个 job 带 ``last_run_at`` / ``last_success_at`` / ``last_status`` /
    ``consecutive_failures`` / ``state``（healthy | failing | stale）。
    """
    stale_after = int(
        stale_after_seconds
        if stale_after_seconds is not None
        else DEFAULT_STALE_AFTER_SECONDS
    )
    now = _utcnow()

    try:
        from modstore_server.db.scheduler_ops import JobRun
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(JobRun)
                .order_by(JobRun.id.desc())
                .limit(max(1, scan_limit))
                .all()
            )
    except Exception:
        logger.exception("get_runtime_status 读取失败")
        return {
            "generated_at": now.isoformat(),
            "stale_after_seconds": stale_after,
            "jobs": [],
            "summary": {"error": "runtime_status_unavailable"},
            "ok": False,
        }

    by_job: dict[str, list[Any]] = {}
    for r in rows:
        by_job.setdefault(r.job_id, []).append(r)

    jobs = [
        _job_summary(job_id, runs, now=now, stale_after=stale_after)
        for job_id, runs in sorted(by_job.items())
    ]

    summary = {
        "total": len(jobs),
        "healthy": sum(1 for j in jobs if j["state"] == "healthy"),
        "failing": sum(1 for j in jobs if j["state"] == "failing"),
        "stale": sum(1 for j in jobs if j["state"] == "stale"),
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
    "get_runtime_status",
    "record_job_run",
    "record_skip",
    "track_job_run",
]
