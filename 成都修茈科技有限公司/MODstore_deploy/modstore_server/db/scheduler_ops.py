"""持久化的 job-run 账本 —— 调度器运行时真相的单一来源。

文件 JSON 心跳只能证明「调度器进程还活着」；它无法区分一个**静默停摆的阶段**
（digest 卡死、心跳照常跳）与一个健康阶段。每次 daily-pipeline 阶段 / cron 任务
执行完都往这里写一行，于是 reader 能按 job 算出 ``last_success``，让悄悄停掉的
任务浮出水面，而不是藏在跳动的心跳后面。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from modstore_server.db.db_base import Base


class JobRun(Base):
    """调度器某个 job/阶段的一次完成（或跳过）执行。"""

    __tablename__ = "scheduler_job_runs"
    __table_args__ = (
        Index("ix_scheduler_job_runs_job_id_id", "job_id", "id"),
        Index("ix_scheduler_job_runs_job_status_id", "job_id", "status", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(128), nullable=False, index=True)
    # success | failed | skipped
    status = Column(String(16), nullable=False, default="success", index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=False, default="")
    # 集群下记录是哪个节点跑的（来自 node_coordinator）；单机留空。
    node_id = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)


class JobHealth(Base):
    """One current summary row per job.

    Health reads use this table instead of ranking ``scheduler_job_runs``.
    ``last_error_code`` is the public code only; the raw ledger text stays on
    ``JobRun`` and is not copied here.
    """

    __tablename__ = "scheduler_job_health"

    job_id = Column(String(128), primary_key=True)
    last_run_id = Column(Integer, nullable=False, index=True)
    last_status = Column(String(16), nullable=False, default="")
    last_started_at = Column(DateTime, nullable=True)
    last_success_started_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    total_runs = Column(Integer, nullable=False, default=0)
    runs_since_success = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(160), nullable=False, default="")


class SchedulerHealthCheckpoint(Base):
    """Highest ledger id already reflected in ``scheduler_job_health``."""

    __tablename__ = "scheduler_health_checkpoint"

    singleton = Column(Integer, primary_key=True, default=1)
    summarized_through_id = Column(Integer, nullable=False, default=0)


__all__ = ["JobHealth", "JobRun", "SchedulerHealthCheckpoint"]
