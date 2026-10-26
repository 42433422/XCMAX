"""启动对账收敛中断任务，保留持久队列、有效租约和恢复前的真实回执。"""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
import threading
import types
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import AgentRun, SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.run_repository import (
    set_agent_run_repository_for_tests,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.db.db_base import Base

reconciler = importlib.import_module("app.application.agent_orchestrator.stale_run_reconciler")
task_dispatcher = importlib.import_module("app.application.agent_orchestrator.task_dispatcher")


@pytest.fixture(autouse=True)
def _offline_recovery(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("restart recovery tests prohibit network/model access")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)


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
    # 显式注册模型，并补齐启动对账所需的队列租约表。
    import app.db.models.agent  # noqa: F401

    Base.metadata.create_all(engine)
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


def test_restore_keeps_completed_backup_receipt_and_later_tasks(tmp_path, monkeypatch):
    import sqlite3

    from app.application.agent_orchestrator.run_models import AgentStep, ToolCall
    from app.domain.shared_services.database_service import DatabaseService

    engine, factory, repo = _make_repo(tmp_path, "restore-audit.db")
    service = DatabaseService()
    live = tmp_path / "restore-audit.db"
    monkeypatch.setattr(service, "_get_db_path", lambda: str(live))
    monkeypatch.setattr(service, "_get_backup_dir", lambda: str(tmp_path))
    try:
        set_agent_run_repository_for_tests(repo)
        with engine.begin() as db:
            db.exec_driver_sql("pragma journal_mode=wal")
            db.exec_driver_sql("create table restore_probe(price real)")
            db.exec_driver_sql("insert into restore_probe values(12.5)")
        step = AgentStep("backup", "system_maintenance", "backup_database", status="running")
        run = AgentRun(
            user_id="2",
            message="备份数据库",
            intent="database_backup",
            status="running",
        )
        run.steps = [step]
        repo.save(run)
        snapshot = service.backup_database()
        assert snapshot["success"] is True
        step.status = "completed"
        step.output = {"success": True, "filename": snapshot["filename"]}
        run.tool_calls = [
            ToolCall(
                step.step_id,
                "backup",
                "system_maintenance",
                "backup_database",
                status="completed",
                output=step.output,
            )
        ]
        run.status = "completed"
        repo.save(run)
        queued = AgentRun(user_id="other", message="稍后执行", status="queued")
        repo.save(queued)
        failed = AgentRun(
            user_id="2", message="原始失败", status="failed", error="审批请求创建失败"
        )
        repo.save(failed)
        receipts = {item.run_id: repo.get(item.run_id).to_dict() for item in (run, queued, failed)}
        with engine.begin() as db:
            db.exec_driver_sql("update restore_probe set price=13.75")
        assert service.restore_database(snapshot["file_path"])["success"] is True
        assert reconciler.reconcile_stale_running_runs(now=_iso(300)) == 0
        for item in (run, queued, failed):
            assert repo.get(item.run_id).to_dict() == receipts[item.run_id]
            assert (
                repo.get_task(user_id=item.user_id, task_id=item.run_id, tenant_id="").status
                == item.status
            )
        with sqlite3.connect(live) as reopened:
            assert reopened.execute("select price from restore_probe").fetchone()[0] == 12.5
            assert reopened.execute("pragma integrity_check").fetchone()[0] == "ok"
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
        from app.application.agent_orchestrator.run_models import AgentStep

        leased.steps = [AgentStep("write", "sales", "quote", status="running")]
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
        assert "non_retryable" not in repo.get(leased.run_id).metadata
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


@pytest.mark.parametrize(
    "tool,action,persisted_idempotent,step_status,trace_mode,unsafe",
    [
        ("sales", "quote", True, "running", "", True),
        ("business_db", "read", False, "running", "", True),
        ("unregistered", "write", True, "running", "", True),
        ("business_db", "read", True, "running", "", False),
        ("sales", "quote", False, "completed", "", False),
        ("business_db", "read", True, "completed", "legacy_planner_run", True),
        (
            "business_db",
            "read",
            True,
            "completed",
            "legacy_planner_run_with_tools",
            True,
        ),
    ],
)
def test_startup_recovery_requires_both_persisted_and_current_replay_safety(
    tmp_path, tool, action, persisted_idempotent, step_status, trace_mode, unsafe
):
    from app.application.agent_orchestrator.run_models import AgentStep

    engine, factory, repo = _make_repo(tmp_path, "replay-safety.db")
    try:
        set_agent_run_repository_for_tests(repo)
        step = AgentStep(
            "original",
            tool,
            action,
            idempotent=persisted_idempotent,
            status=step_status,
            output={"success": True} if step_status == "completed" else {},
        )
        run = AgentRun(
            user_id="synthetic",
            message="restart boundary",
            status="running",
            steps=[step],
        )
        if trace_mode:
            run.metadata["trace_mode"] = trace_mode
        repo.save(run)
        _backdate_run(factory, run.run_id, status="running", updated_at=_iso(-300))

        assert reconciler.reconcile_stale_running_runs() == 1
        with sqlite3.connect(tmp_path / "replay-safety.db") as reopened:
            stored = json.loads(
                reopened.execute(
                    "SELECT payload_json FROM agent_runs WHERE run_id=?", (run.run_id,)
                ).fetchone()[0]
            )
        assert stored["status"] == "failed"
        assert stored["steps"] == [step.to_dict()]
        assert bool(stored["metadata"].get("non_retryable")) is unsafe
        if unsafe:
            assert stored["metadata"]["recovery"]["state"] == "manual_reconciliation_required"
            assert stored["metadata"]["recovery"]["step_ids"] == (
                [step.step_id] if step_status == "running" else []
            )
        else:
            assert "recovery" not in stored["metadata"]
    finally:
        set_agent_run_repository_for_tests(None)
        engine.dispose()


@pytest.mark.parametrize("previous_recovery", [None, {"state": "waiting", "original": "keep"}])
def test_committed_write_process_exit_startup_dispatch_and_retry_never_reexecute(
    tmp_path, monkeypatch, previous_recovery
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_models import AgentStep, ToolCall

    path = tmp_path / "crashed-writer.db"
    engine, factory, repo = _make_repo(tmp_path, path.name)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    step = AgentStep("quote", "sales", "quote", status="running", idempotent=True)
    run = AgentRun(
        user_id="synthetic",
        message="original committed write",
        status="running",
        steps=[step],
    )
    run.tool_calls = [
        ToolCall(step.step_id, step.node_id, step.tool_id, step.action, status="running")
    ]
    if previous_recovery:
        run.metadata["recovery"] = dict(previous_recovery)
    repo.save(run)
    queue.enqueue(run)
    assert queue.claim("exited-process", lease_seconds=60) is not None
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE synthetic_effects(id INTEGER PRIMARY KEY, run_id TEXT)")
        db.exec_driver_sql(
            "UPDATE agent_task_executions SET lease_expires_at=? WHERE run_id=?",
            (_iso(-300), run.run_id),
        )
    _backdate_run(factory, run.run_id, status="running", updated_at=_iso(-300))
    # The child commits its effect, then exits without returning a tool receipt.
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os,sqlite3,sys; db=sqlite3.connect(sys.argv[1]); "
            "db.execute('INSERT INTO synthetic_effects(run_id) VALUES(?)',(sys.argv[2],)); "
            "db.commit(); os._exit(23)",
            str(path),
            run.run_id,
        ],
        check=False,
        timeout=10,
        capture_output=True,
    )
    assert child.returncode == 23, child.stderr

    unexpected_dispatches = []

    def forbidden(*args, **kwargs):
        unexpected_dispatches.append((args, kwargs))
        raise AssertionError("an unknown original write must never reach planning or tool dispatch")

    monkeypatch.setattr(AgentOrchestrator, "_plan", forbidden)
    finished = threading.Event()
    original_finish = queue.finish

    def finish(*args, **kwargs):
        result = original_finish(*args, **kwargs)
        finished.set()
        return result

    monkeypatch.setattr(queue, "finish", finish)
    dispatcher = task_dispatcher.AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repo,
        max_workers=1,
        poll_seconds=0.02,
        orchestrator_factory=lambda repository: AgentOrchestrator(
            repository=repository,
            tool_executor=types.SimpleNamespace(execute=forbidden),
        ),
    )
    monkeypatch.setattr(task_dispatcher, "get_agent_task_dispatcher", lambda: dispatcher)
    set_agent_run_repository_for_tests(repo)
    try:
        assert task_dispatcher.start_agent_task_dispatcher() is dispatcher
        assert finished.wait(5), "real dispatcher did not settle the expired original claim"
        dispatcher.stop()
        stored = repo.get(run.run_id)
        assert stored.status == "failed" and stored.metadata["non_retryable"] is True
        assert stored.metadata["recovery"]["state"] == "manual_reconciliation_required"
        if previous_recovery:
            assert stored.metadata["recovery"]["original"] == "keep"
        with pytest.raises(ValueError, match="人工核对"):
            AgentOrchestrator(repository=repo).retry_run(run.run_id)
        assert unexpected_dispatches == []
        with sqlite3.connect(path) as reopened:
            assert reopened.execute("SELECT run_id FROM synthetic_effects").fetchall() == [
                (run.run_id,)
            ]
            rows = reopened.execute("SELECT status,payload_json FROM agent_runs").fetchall()
            assert len(rows) == 1 and rows[0][0] == "failed"
            payload = json.loads(rows[0][1])
            assert payload["steps"][0]["status"] == "running"
            assert payload["steps"][0]["output"] == {}
            assert len(payload["tool_calls"]) == 1
            assert reopened.execute("SELECT status FROM agent_tasks").fetchall() == [("failed",)]
        execution = queue.get(run.run_id)
        assert execution.state == "failed"
        assert execution.execution_count == 2 and execution.recovery_count == 1
    finally:
        dispatcher.stop()
        set_agent_run_repository_for_tests(None)
        engine.dispose()
