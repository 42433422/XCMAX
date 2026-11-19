"""Process death, durable native checkpoints and safe same-task continuation."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import (
    AgentOrchestrator,
    AgentRun,
    SQLAlchemyAgentRunRepository,
    task_dispatcher,
)
from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _run(actor, *, status="queued", completed_write=False):
    first = WorkflowNode(
        node_id="first",
        tool_id="products",
        action="query",
        params={"keyword": "first"},
        risk="low",
        idempotent=True,
    )
    if completed_write:
        first = WorkflowNode(
            node_id="first",
            tool_id="sales",
            action="quote",
            risk="high",
            idempotent=False,
            params={
                "customer_id": 1,
                "items": [{"product_id": 2, "quantity": 1, "unit_price": 50}],
            },
        )
    plan = PlanGraph(
        plan_id="durable-plan",
        intent="query",
        nodes=[
            first,
            WorkflowNode(
                node_id="second",
                tool_id="products",
                action="query",
                params={"keyword": "second"},
                risk="low",
                idempotent=True,
                depends_on=["first"],
            ),
        ],
    )
    run = AgentRun(
        user_id=str(actor.user_id),
        message="durable continuation",
        status=status,
        plan_id=plan.plan_id,
    )
    run.steps = [AgentOrchestrator._step_from_node(node) for node in plan.nodes]
    # Persist exactly the normalized, server-owned replay and approval contract.
    for node, step in zip(plan.nodes, run.steps, strict=True):
        node.risk, node.idempotent = step.risk, step.idempotent
    task_id = "task-" + run.run_id
    plan.metadata["source"] = "unified_task_api"
    run.metadata.update(
        runtime_context={**actor.context, "conversation_id": task_id, "workspace_id": task_id},
        plan=plan_to_dict(plan),
        task_context={"task_id": task_id},
        task_request={"tool_id": first.tool_id, "action": first.action},
    )
    if completed_write:
        run.steps[0].status = "completed"
        run.steps[0].output = {"success": True, "quote_id": 81}
        run.steps[1].status = "failed"
    return run


def _repositories(actor):
    return (
        SQLAlchemyAgentRunRepository(session_factory=actor.factory),
        SQLAlchemyTaskExecutionRepository(session_factory=actor.factory),
    )


def _finish_with_startup(monkeypatch, repository, queue, execute, run_id):
    dispatcher = task_dispatcher.AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        max_workers=2,
        poll_seconds=0.02,
        orchestrator_factory=lambda repo: AgentOrchestrator(
            repository=repo, tool_executor=SimpleNamespace(execute=execute) if execute else None
        ),
    )
    monkeypatch.setattr(task_dispatcher, "get_agent_task_dispatcher", lambda: dispatcher)
    set_agent_run_repository_for_tests(repository)
    try:
        assert task_dispatcher.start_agent_task_dispatcher() is dispatcher
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and queue.get(run_id).state in {
            "queued",
            "running",
            "claimed",
        }:
            time.sleep(0.02)
        stored = repository.get(run_id)
        assert stored.status == "completed", stored.to_dict()
        assert queue.get(run_id).state == "succeeded"
        return stored
    finally:
        dispatcher.stop()
        set_agent_run_repository_for_tests(None)


def test_real_executor_resumes_crashed_read_claim_under_replacement_queue_lease(
    trusted_actor, tmp_path, monkeypatch
):
    from app.application.agent_orchestrator import tool_permission

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = repository.save(_run(actor))
    queue.enqueue(run)
    claim_path = tmp_path / "tool-claims.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(claim_path))
    script = tmp_path / "read_worker.py"
    script.write_text("""
import os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository, tool_permission
from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_sql_repository import SQLAlchemyTaskExecutionRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
factory = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))
repo = SQLAlchemyAgentRunRepository(session_factory=factory)
queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
execution = queue.claim("crashed-reader", lease_seconds=60)
run = repo.get(sys.argv[1])
run.status = run.steps[0].status = "running"
repo.save(run)
tool_permission.finish_idempotent_replay = lambda *args: os._exit(23)
with worker_claim_scope(repo, execution, execution.lease_owner):
    context = {**run.metadata["runtime_context"], "run_id": run.run_id,
               **task_execution_context(run, run.steps[0])}
    result = AgentToolExecutor().execute(run.steps[0], runtime_context=context)
    raise AssertionError(result)
""")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    child = subprocess.run(
        [sys.executable, str(script), run.run_id], timeout=25, capture_output=True, env=env
    )
    assert child.returncode == 23, (child.stdout.decode(), child.stderr.decode())
    with sqlite3.connect(claim_path) as db:
        old_owner, inflight = db.execute("SELECT owner, inflight FROM tool_idempotency").fetchone()
        assert inflight == 1 and ":read-lease-v1:" in old_owner
    interrupted = repository.get(run.run_id)
    assert interrupted.steps[0].status == "running"
    path = os.environ["DATABASE_URL"].removeprefix("sqlite:///")
    expired = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE agent_runs SET updated_at=? WHERE run_id=?", (expired, run.run_id))
        db.execute(
            "UPDATE agent_task_executions SET lease_expires_at=? WHERE run_id=?",
            (expired, run.run_id),
        )
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    try:
        from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

        stored = _finish_with_startup(
            monkeypatch, repository, queue, AgentToolExecutor().execute, run.run_id
        )
        assert all(step.status == "completed" for step in stored.steps)
        assert queue.get(run.run_id).execution_count == 2
        with sqlite3.connect(claim_path) as db:
            receipts = db.execute(
                "SELECT owner, inflight, output_json FROM tool_idempotency"
            ).fetchmany(3)
        assert len(receipts) == 2
        assert all(
            owner != old_owner and flag == 0 and json.loads(body)["success"]
            for owner, flag, body in receipts
        )
    finally:
        tool_permission.clear_idempotent_replay_for_tests()


def test_read_takeover_fences_live_duplicate_and_stale_worker_completion(
    trusted_actor, tmp_path, monkeypatch
):
    from app.application.agent_orchestrator import tool_permission
    from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost

    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = repository.save(_run(actor))
    queue.enqueue(run)
    first = queue.claim("first", lease_seconds=60)
    path = tmp_path / "claims.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(path))
    context = {**actor.context, "run_id": run.run_id, **task_execution_context(run, run.steps[0])}
    params = run.steps[0].params
    try:
        with worker_claim_scope(repository, first, first.lease_owner):
            key, replay = tool_permission.begin_idempotent_replay(
                context, "products", "query", params
            )
            assert replay is None
            assert (
                tool_permission.begin_idempotent_replay(context, "products", "query", params)[1][
                    "error_code"
                ]
                == "idempotency_in_progress"
            )
        with actor.factory.begin() as db:
            from app.db.models.agent import AgentTaskExecutionRecord

            db.get(AgentTaskExecutionRecord, run.run_id).lease_expires_at = (
                datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat()
        second = queue.claim("second", lease_seconds=60)
        assert second.execution_count == first.execution_count + 1
        with worker_claim_scope(repository, second, second.lease_owner):
            assert tool_permission.begin_idempotent_replay(
                context, "products", "query", params
            ) == (key, None)
        with worker_claim_scope(repository, first, first.lease_owner):
            with pytest.raises(WorkerLeaseLost):
                tool_permission.begin_idempotent_replay(context, "products", "query", params)
            with pytest.raises(WorkerLeaseLost):
                tool_permission.finish_idempotent_replay(key, {"success": True, "data": ["late"]})
        with worker_claim_scope(repository, second, second.lease_owner):
            tool_permission.finish_idempotent_replay(key, {"success": True, "data": ["current"]})
        with sqlite3.connect(path) as db:
            assert json.loads(db.execute("SELECT output_json FROM tool_idempotency").fetchone()[0])[
                "data"
            ] == ["current"]
    finally:
        tool_permission.clear_idempotent_replay_for_tests()


@pytest.mark.parametrize("desktop", [False, True])
@pytest.mark.parametrize("crash_at", ["next_tool", "receipt"])
def test_process_exit_real_startup_resumes_native_checkpoint_without_repeating_receipt(
    trusted_actor,
    tmp_path,
    monkeypatch,
    desktop,
    crash_at,
):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = repository.save(_run(actor))
    queue.enqueue(run)
    path = os.environ["DATABASE_URL"].removeprefix("sqlite:///")
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE recovery_effects(node TEXT, key TEXT)")
    script = tmp_path / "crashing_worker.py"
    script.write_text("""
import os, sqlite3, sys, time
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.application.agent_orchestrator import AgentOrchestrator, SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator import task_dispatcher
from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.task_execution_sql_repository import SQLAlchemyTaskExecutionRepository
factory = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))
repo = SQLAlchemyAgentRunRepository(session_factory=factory)
queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
def execute(step, *, runtime_context):
    if step.node_id == "second":
        os._exit(23)
    with sqlite3.connect(sys.argv[1]) as db:
        db.execute("INSERT INTO recovery_effects VALUES (?,?)", (step.node_id, runtime_context["idempotency_key"]))
    return {"success": True, "data": [{"id": 1}]}
def orchestrator(repository):
    service = AgentOrchestrator(repository=repository, tool_executor=SimpleNamespace(execute=execute))
    if sys.argv[2] == "receipt":
        service._step_execution.observe = lambda *a, **kw: os._exit(23)
    return service
dispatcher = task_dispatcher.AgentTaskDispatcher(
    execution_repository=queue, run_repository=repo, max_workers=1, poll_seconds=0.02,
    orchestrator_factory=orchestrator)
set_agent_run_repository_for_tests(repo)
task_dispatcher.set_agent_task_dispatcher_for_tests(dispatcher)
task_dispatcher.start_agent_task_dispatcher()
time.sleep(15)
dispatcher.stop()
raise SystemExit(99)
""")
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (
                str(Path(__file__).resolve().parents[2]),
                child_env.get("PYTHONPATH", ""),
            ),
        )
    )
    child = subprocess.run(
        [sys.executable, str(script), path, crash_at],
        timeout=25,
        capture_output=True,
        env=child_env,
    )
    assert child.returncode == 23, (child.stdout.decode(), child.stderr.decode())
    interrupted = repository.get(run.run_id)
    receipt = copy.deepcopy(interrupted.steps[0].to_dict())
    assert receipt["status"] == "completed"
    assert interrupted.steps[1].status == ("running" if crash_at == "next_tool" else "pending")
    checkpoint_thread = interrupted.metadata["checkpoint"]["thread_id"]
    expired = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id=?", (checkpoint_thread,)
            ).fetchone()[0]
            > 0
        )
        db.execute("UPDATE agent_runs SET updated_at=? WHERE run_id=?", (expired, run.run_id))
        db.execute(
            "UPDATE agent_task_executions SET lease_expires_at=? WHERE run_id=?",
            (expired, run.run_id),
        )
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1" if desktop else "0")

    def execute(step, *, runtime_context):
        with sqlite3.connect(path) as db:
            db.execute(
                "INSERT INTO recovery_effects VALUES (?,?)",
                (step.node_id, runtime_context["idempotency_key"]),
            )
        return {"success": True, "data": [{"id": 2}]}

    stored = _finish_with_startup(monkeypatch, repository, queue, execute, run.run_id)
    assert stored.steps[0].to_dict() == receipt
    assert [step.step_id for step in stored.steps] == [step.step_id for step in run.steps]
    assert stored.metadata["checkpoint"]["thread_id"] == checkpoint_thread
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT node,key FROM recovery_effects ORDER BY node").fetchmany(
            len(run.steps) + 1
        ) == [
            (step.node_id, task_execution_context(run, step)["idempotency_key"])
            for step in run.steps
        ]
    assert queue.get(run.run_id).recovery_count == 1


def test_concurrent_retry_preserves_completed_write_and_atomically_requeues_same_run(
    trusted_actor, monkeypatch
):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    original = repository.save(_run(actor, status="failed", completed_write=True))
    queue.enqueue(original)
    queue.transition(original.run_id, "failed", error_code="tool_failed")
    before = copy.deepcopy(original.steps[0].to_dict())

    def retry(_):
        return AgentOrchestrator(repository=repository).retry_run(
            original.run_id,
            requested_by=str(actor.user_id),
            auto_execute=False,
            runtime_context=actor.context,
            authenticated_binding=actor.principal.mod_authorization,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        retried = list(pool.map(retry, range(2)))
    assert {item.run_id for item in retried} == {original.run_id}
    assert all(item.status == "queued" for item in retried)
    assert queue.get(original.run_id).state == "queued"
    assert len(repository.list_recent(user_id=str(actor.user_id))) == 1
    assert (
        len(
            [
                e
                for e in repository.get(original.run_id).events
                if e.event_type == "run.continuation_queued"
            ]
        )
        == 1
    )
    calls = []

    def execute(step, *, runtime_context):
        calls.append((step.node_id, runtime_context["idempotency_key"]))
        return {"success": True, "data": []}

    stored = _finish_with_startup(monkeypatch, repository, queue, execute, original.run_id)
    assert stored.steps[0].to_dict() == before
    assert calls == [
        ("second", task_execution_context(original, original.steps[1])["idempotency_key"])
    ]


@pytest.mark.parametrize("condition", ["unknown", "plan_changed", "write_pending", "live_lease"])
def test_retry_rejects_unverified_original_state_without_queue_changes(trusted_actor, condition):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = _run(actor, status="failed", completed_write=True)
    if condition == "unknown":
        run.steps[1].output = {"success": False, "outcome": "unknown"}
    elif condition == "plan_changed":
        run.steps[1].params["keyword"] = "new business intent"
    elif condition == "write_pending":
        run.steps[0].status, run.steps[0].output = "pending", {}
    repository.save(run)
    queue.enqueue(run)
    if condition == "live_lease":
        assert queue.claim("live-worker", lease_seconds=60) is not None
    else:
        queue.transition(run.run_id, "failed", error_code="tool_failed")
    before = repository.get(run.run_id).to_dict()
    execution = queue.get(run.run_id).to_dict()
    with pytest.raises(ValueError):
        AgentOrchestrator(repository=repository).retry_run(
            run.run_id,
            requested_by=str(actor.user_id),
            auto_execute=False,
            authenticated_binding=actor.principal.mod_authorization,
        )
    assert repository.get(run.run_id).to_dict() == before
    assert queue.get(run.run_id).to_dict() == execution


def test_completed_receipt_settles_open_effect_before_another_worker_takes_lease(trusted_actor):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = _run(actor, status="running", completed_write=True)
    repository.save(run)
    queue.enqueue(run)
    assert queue.claim("dead-worker", lease_seconds=60)
    queue.mark_open_effect(run.run_id, run.steps[0].step_id)
    future = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
    claimed = queue.claim("replacement", lease_seconds=60, now=future)
    assert claimed is not None and claimed.lease_owner == "replacement"
    assert queue.lifecycle(run.run_id)["effects"] == []


def test_native_checkpoint_identity_includes_tenant_user_run_and_plan(trusted_actor):
    from app.application.workflow.workflow_types import plan_from_dict
    from app.infrastructure.workflow.checkpoint_bridge import run_checkpoint_thread

    run = _run(trusted_actor())
    plan = plan_from_dict(run.metadata["plan"])
    identity = run_checkpoint_thread(run, plan, parallel=True)
    changed = copy.deepcopy(run)
    changed.metadata["runtime_context"]["tenant_id"] = "different"
    assert run_checkpoint_thread(changed, plan, parallel=True) != identity
    changed = copy.deepcopy(run)
    changed.user_id = "different"
    assert run_checkpoint_thread(changed, plan, parallel=True) != identity
    changed.run_id = "another-run"
    assert run_checkpoint_thread(changed, plan, parallel=True) != identity
    plan.nodes[1].params["keyword"] = "changed-plan"
    assert run_checkpoint_thread(run, plan, parallel=True) != identity


def test_retry_queue_failure_rolls_back_receipt_and_terminal_transition(trusted_actor, monkeypatch):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    original = repository.save(_run(actor, status="failed", completed_write=True))
    queue.enqueue(original)
    queue.transition(original.run_id, "failed", error_code="tool_failed")
    before = repository.get(original.run_id).to_dict()
    execution = queue.get(original.run_id).to_dict()
    enqueue = SQLAlchemyTaskExecutionRepository.enqueue_in_session

    def fail(*args, **kwargs):
        enqueue(*args, **kwargs)
        raise RuntimeError("queue commit rejected")

    monkeypatch.setattr(SQLAlchemyTaskExecutionRepository, "enqueue_in_session", fail)
    with pytest.raises(RuntimeError, match="queue commit rejected"):
        AgentOrchestrator(repository=repository).retry_run(
            original.run_id,
            requested_by=str(actor.user_id),
            auto_execute=False,
            authenticated_binding=actor.principal.mod_authorization,
        )
    assert repository.get(original.run_id).to_dict() == before
    assert queue.get(original.run_id).to_dict() == execution


def test_unknown_checkpoint_version_fails_before_tool_dispatch(trusted_actor):
    actor = trusted_actor(role="admin")
    repository, _ = _repositories(actor)
    run = _run(actor)
    run.metadata["checkpoint"] = {"backend": "langgraph", "schema_version": 999}
    repository.save(run)
    calls = []
    service = AgentOrchestrator(
        repository=repository,
        tool_executor=SimpleNamespace(execute=lambda *args, **kwargs: calls.append(args)),
    )
    stored = service.execute_dispatched_run(run.run_id)
    assert stored.status == "blocked" and "版本" in stored.error
    assert calls == []


@pytest.mark.skipif(
    not os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL"), reason="requires CI PostgreSQL service"
)
def test_postgres_native_saver_concurrent_setup_and_reopen_preserves_host_schema():
    import uuid

    from langgraph.graph import END, START, StateGraph
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from typing_extensions import TypedDict

    from app.infrastructure.workflow.checkpoint_bridge import open_run_checkpointer

    class State(TypedDict):
        count: int

    builder = StateGraph(State)
    builder.add_node("first", lambda state: {"count": state["count"] + 1})
    builder.add_node("second", lambda state: {"count": state["count"] + 1})
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    url = os.environ["XCAGI_TEST_AGENT_POSTGRES_URL"]
    admin = create_engine(url)
    schema = "native_recovery_" + uuid.uuid4().hex
    with admin.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=15000"
        },
    )
    repository = SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine))
    try:

        def interrupted(index):
            config = {"configurable": {"thread_id": f"{schema}:{index}"}}
            with open_run_checkpointer(repository) as saver:
                graph = builder.compile(checkpointer=saver)
                assert graph.invoke(
                    {"count": 0}, config, interrupt_after=["first"], durability="sync"
                ) == {"count": 1}
                assert graph.get_state(config).next == ("second",)
            return config

        with ThreadPoolExecutor(max_workers=2) as pool:
            configs = list(pool.map(interrupted, range(2)))
        with open_run_checkpointer(repository) as reopened:
            graph = builder.compile(checkpointer=reopened)
            for config in configs:
                assert graph.invoke(None, config, durability="sync") == {"count": 2}
                assert graph.get_state(config).next == ()
        with engine.connect() as db:
            assert (
                db.execute(text("SELECT COUNT(DISTINCT thread_id) FROM checkpoints")).scalar() == 2
            )
            tables = set(
                db.execute(
                    text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=:schema"),
                    {"schema": schema},
                ).scalars()
            )
            assert {"checkpoints", "checkpoint_writes", "checkpoint_blobs"} <= tables
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
