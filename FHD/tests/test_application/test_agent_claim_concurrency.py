"""审计 R11（2026-09-05 报告）：Agent 重复执行防护的并发竞态证明。

审批令牌有两道防线：
1. Redis SETNX 一次性消费（跨进程，Redis 可用时）；
2. 执行阶段 DB 条件更新 CAS（Redis 断连时的兜底，见 task_execution_sql_repository.claim）。

本文件验证第二道防线：多个 worker 并发认领同一排队任务时，
只会有一个 worker 成功、execution_count 只 +1，其余全部拿不到任务，
从而保证「仅一次业务效果」。Redis 断连（进程内集合互不可见）时该性质仍成立。
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)


def _pg_url() -> str:
    return os.environ.get("ETL_TEST_POSTGRES_URL", "")


def _make_engine(tmp_path):
    url = _pg_url()
    if url:
        schema = f"pm_claim_{uuid.uuid4().hex}"
        admin = create_engine(url)
        from sqlalchemy import text

        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        return engine, (admin, schema)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'claim.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine, (None, "")


@pytest.mark.parametrize("workers", [2, 8])
def test_concurrent_claim_admits_exactly_one_worker(workers: int, tmp_path) -> None:
    engine, (admin, schema) = _make_engine(tmp_path)
    try:
        factory = sessionmaker(bind=engine)
        repo = SQLAlchemyTaskExecutionRepository(session_factory=factory)
        run = AgentRun(user_id="owner", message="并发审批任务", status="queued")
        run.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
        run.metadata["task_context"] = {"task_id": f"task-{uuid.uuid4().hex}"}
        queued = repo.enqueue(run, requested_by="owner", priority=10)
        available = queued.available_at

        # 每个 worker 用独立仓储实例，模拟多进程各自持有连接/进程内状态
        # （Redis 断连时进程内已消费集合互不可见，只剩 DB CAS 兜底）。
        def attempt(index: int):
            worker_repo = SQLAlchemyTaskExecutionRepository(session_factory=factory)
            return worker_repo.claim(f"worker-{index}", lease_seconds=30, now=available)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(attempt, range(workers)))

        winners = [r for r in results if r is not None]
        assert len(winners) == 1, f"期望仅一个 worker 认领成功，实际 {len(winners)}"
        assert winners[0].execution_count == 1
        assert winners[0].state == "claimed"
        # 其余 worker 全部拿不到任务，不会重复执行。
        assert all(r is None for r in results if r is not winners[0])
    finally:
        engine.dispose()
        if admin is not None:
            from sqlalchemy import text

            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_second_claim_after_release_recovers_only_once(tmp_path) -> None:
    """租约过期后允许恢复认领，但恢复也只发生一次、计数单调递增。"""
    from datetime import datetime, timedelta

    engine, (admin, schema) = _make_engine(tmp_path)
    try:
        factory = sessionmaker(bind=engine)
        repo = SQLAlchemyTaskExecutionRepository(session_factory=factory)
        run = AgentRun(user_id="owner", message="租约恢复任务", status="queued")
        run.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
        run.metadata["task_context"] = {"task_id": f"task-{uuid.uuid4().hex}"}
        queued = repo.enqueue(run, requested_by="owner", priority=10)
        base = datetime.fromisoformat(queued.available_at.replace("Z", "+00:00"))

        first = repo.claim("worker-a", lease_seconds=10, now=base.isoformat())
        assert first is not None and first.execution_count == 1
        # 未过期时其他 worker 拿不到。
        assert repo.claim("worker-b", lease_seconds=10, now=base.isoformat()) is None
        # 过期后仅一个恢复认领成功。
        later = (base + timedelta(seconds=30)).isoformat()
        with ThreadPoolExecutor(max_workers=4) as pool:
            recovered = list(
                pool.map(
                    lambda i: SQLAlchemyTaskExecutionRepository(session_factory=factory).claim(
                        f"recover-{i}", lease_seconds=10, now=later
                    ),
                    range(4),
                )
            )
        winners = [r for r in recovered if r is not None]
        assert len(winners) == 1
        assert winners[0].execution_count == 2
        assert winners[0].recovery_count == 1
    finally:
        engine.dispose()
        if admin is not None:
            from sqlalchemy import text

            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()
