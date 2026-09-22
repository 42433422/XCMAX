"""M15 回归：后端中断遗留的 running 任务必须在启动对账时收敛为 failed。

修复前本文件整体 ImportError（``stale_run_reconciler`` 不存在），即测试失败。
修复后须同时满足：
- 超过心跳窗口的在途 run/task 被收敛为 failed，且带可检索的 error_code；
- 仍可恢复的 queued run 不被失败（不破坏持久队列）；
- 仍持有未过期租约的 run 交由既有重认领机制，不被启动对账改写。
"""

from __future__ import annotations

import importlib
import json
import types
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentRun, SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.run_repository import (
    set_agent_run_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)

reconciler = importlib.import_module("app.application.agent_orchestrator.stale_run_reconciler")
task_dispatcher = importlib.import_module("app.application.agent_orchestrator.task_dispatcher")


def _iso(offset_seconds: float = 0.0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat()


def _backdate_run(factory, run_id: str, *, status: str, updated_at: str) -> None:
    from app.db.models.agent import AgentRunRecord

    with factory.begin() as db:
        record = db.get(AgentRunRecord, run_id)
        payload = json.loads(record.payload_json or "{}")
        payload["status"] = status
        payload["updated_at"] = updated_at
        record.status = status
        record.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        record.updated_at = updated_at


def _make_repo(tmp_path, name: str):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    factory = sessionmaker(bind=engine)
    return engine, factory, SQLAlchemyAgentRunRepository(session_factory=factory)


def test_interrupted_running_run_and_task_are_converged(tmp_path) -> None:
    engine, factory, repo = _make_repo(tmp_path, "stale.db")
    try:
        set_agent_run_repository_for_tests(repo)
        run = AgentRun(
            user_id="u1",
            message="给 R2验收客户有限公司 生成送货单",
            status="running",
            intent="shipment_orders_generate",
        )
        run.metadata["task_context"] = {"task_id": "task-stale"}
        repo.save(run)
        stale_at = _iso(-300)
        _backdate_run(factory, run.run_id, status="running", updated_at=stale_at)

        reconciled = reconciler.reconcile_stale_running_runs(stale_after_seconds=60, now=_iso())

        assert reconciled == 1
        stored = repo.get(run.run_id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.metadata["interrupted"]["error_code"] == "interrupted_by_restart"
        assert stored.metadata["interrupted"]["previous_status"] == "running"
        task = repo.get_task(user_id="u1", task_id="task-stale", tenant_id="")
        assert task is not None
        assert task.status == "failed"
        assert task.attention_state == "failed"
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


def test_recoverable_queue_and_live_lease_are_left_alone(tmp_path) -> None:
    engine, factory, repo = _make_repo(tmp_path, "keep.db")
    try:
        set_agent_run_repository_for_tests(repo)
        queued = AgentRun(user_id="u1", message="排队中的任务", status="queued")
        repo.save(queued)
        _backdate_run(factory, queued.run_id, status="queued", updated_at=_iso(-600))

        leased = AgentRun(user_id="u1", message="租约仍有效", status="running")
        repo.save(leased)
        executions = SQLAlchemyTaskExecutionRepository(session_factory=factory)
        executions.enqueue(leased)
        assert executions.claim("owner-1", lease_seconds=600) is not None
        _backdate_run(factory, leased.run_id, status="running", updated_at=_iso(-600))

        fresh = AgentRun(user_id="u1", message="刚开始运行", status="running")
        repo.save(fresh)

        assert reconciler.reconcile_stale_running_runs(stale_after_seconds=60, now=_iso()) == 0
        assert repo.get(queued.run_id).status == "queued"
        assert repo.get(leased.run_id).status == "running"
        assert repo.get(fresh.run_id).status == "running"
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


def test_dispatcher_reconciles_before_it_starts_dispatching(monkeypatch) -> None:
    """对账必须发生在 dispatcher 开始认领执行之前，否则中断任务会被并发改写。"""
    calls: list[str] = []
    monkeypatch.setattr(
        reconciler,
        "reconcile_stale_running_runs",
        lambda **kwargs: calls.append("reconcile") or 2,
    )
    monkeypatch.setattr(
        task_dispatcher,
        "get_agent_task_dispatcher",
        lambda: types.SimpleNamespace(start=lambda: calls.append("start")),
    )

    task_dispatcher.start_agent_task_dispatcher()

    assert calls == ["reconcile", "start"]


def test_reconcile_failure_does_not_block_dispatcher_start(monkeypatch) -> None:
    """对账本身出错时只告警，不得让 dispatcher 起不来。"""
    calls: list[str] = []

    def _boom(**kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(reconciler, "reconcile_stale_running_runs", _boom)
    monkeypatch.setattr(
        task_dispatcher,
        "get_agent_task_dispatcher",
        lambda: types.SimpleNamespace(start=lambda: calls.append("start")),
    )

    task_dispatcher.start_agent_task_dispatcher()

    assert calls == ["start"]
