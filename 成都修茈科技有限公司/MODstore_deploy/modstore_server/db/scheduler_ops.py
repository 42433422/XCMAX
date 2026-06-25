"""持久化的 job-run 账本 —— 调度器运行时真相的单一来源。

文件 JSON 心跳只能证明「调度器进程还活着」；它无法区分一个**静默停摆的阶段**
（digest 卡死、心跳照常跳）与一个健康阶段。每次 daily-pipeline 阶段 / cron 任务
执行完都往这里写一行，于是 reader 能按 job 算出 ``last_success``，让悄悄停掉的
任务浮出水面，而不是藏在跳动的心跳后面。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from modstore_server.db.base import Base


class JobRun(Base):
    """调度器某个 job/阶段的一次完成（或跳过）执行。"""

    __tablename__ = "scheduler_job_runs"

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
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


__all__ = ["JobRun"]
