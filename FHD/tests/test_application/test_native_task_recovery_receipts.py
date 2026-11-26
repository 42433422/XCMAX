"""Native task claim handoff and durable receipt recovery."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
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
from app.application.agent_orchestrator.approval_grant import authorization_scope_hash
from app.application.agent_orchestrator.run_repository import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_native_task_recovery import (
    _assert_unverified_not_replayable,
    _ExitingCheckpointExecutor,
    _finish_with_startup,
    _repositories,
    _run,
)


@pytest.mark.parametrize("cleanup_verified", [True, False], ids=["verified", "unverified"])
def test_spawned_elt_checkpoint_transfers_only_the_exact_approved_claim(
    trusted_actor, monkeypatch, tmp_path, cleanup_verified
):
    # Collection can prepend another project's tests package; spawn imports afresh.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    from app.application.agent_orchestrator import tool_process
    from app.application.agent_orchestrator.approval_grant import (
        approval_receipt_claims,
    )
    from app.application.agent_orchestrator.elt_checkpoint_recovery import ELT_CHECKPOINT_PROTOCOL
    from app.application.workflow.workflow_types import plan_fingerprint

    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    node = WorkflowNode(
        "import",
        "elt_import",
        "execute",
        {
            "file_paths": [
                "648777a2-83cb-4b1d-b20f-8370b498032b",
                "648777a2-83cb-4b1d-b20f-8370b498032c",
            ]
        },
        risk="high",
    )
    plan = PlanGraph(
        "original-elt",
        "导入",
        nodes=[node],
        metadata={"durable_elt_batch": True, "approval_required_node_ids": [node.node_id]},
    )
    step = AgentOrchestrator._step_from_node(node)
    node.idempotent = step.idempotent
    run = AgentRun(
        user_id=str(actor.user_id),
        message=plan.intent,
        status="queued",
        plan_id=plan.plan_id,
        steps=[step],
    )
    run.metadata.update(
        plan=plan_to_dict(plan),
        runtime_context=actor.context,
        execution_authorization_scope=authorization_scope_hash(actor.context),
        dispatch={
            "approved_step_id": step.step_id,
            "elt_checkpoint_protocol": ELT_CHECKPOINT_PROTOCOL,
        },
        approval_receipt={
            "queue_approval": "workspace_claim",
            "approval_request_id": "test",
            "step_id": step.step_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "approved_by": run.user_id,
            "plan_sha256": plan_fingerprint(plan),
        },
    )
    run.metadata["approval_receipt"].update(approval_receipt_claims(run, step))
    repository.save(run)
    queue.enqueue(run)
    old = queue.claim("old", lease_seconds=60)
    dispatcher = task_dispatcher.AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda repo: AgentOrchestrator(
            repository=repo, tool_executor=_ExitingCheckpointExecutor()
        ),
    )
    fixture = os.environ["DATABASE_URL"].removeprefix("sqlite:///")
    with sqlite3.connect(fixture) as db:
        db.execute("create table elt_checkpoint_test (file int primary key)")
    marker_db = tmp_path / "elt-tool-claims.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(marker_db))
    monkeypatch.setattr(tool_process, "_caller_business_db_url", lambda: "")
    monkeypatch.setattr(tool_process.tempfile, "tempdir", str(tmp_path))
    original_close = tool_process._OwnedWorker.close
    observed_exits = []

    def inspect_fixture_exit(worker, **kwargs):
        clean = original_close(worker, **kwargs)
        if worker.worker_exited and worker.worker_exitcode == 23:
            observed_exits.append(clean)
            # Lose the cleanup proof only after the real supervisor has reaped
            # this fixture. A missing proof must still forbid checkpoint reuse.
            return clean and cleanup_verified
        return clean

    monkeypatch.setattr(tool_process._OwnedWorker, "close", inspect_fixture_exit)
    dispatcher._execute_claim(old, "old")
    assert observed_exits == [True]
    stored = repository.get(run.run_id)
    if not cleanup_verified:
        assert stored.status == "blocked", stored.steps[0].output
        assert stored.steps[0].output["error_code"] == "tool_worker_exited"
        assert stored.steps[0].output["reconciliation_evidence"]["cleanup_unresolved"] is True
        assert stored.steps[0].output["reconciliation_required"] is True
        assert stored.steps[0].output == stored.tool_calls[0].output
        assert stored.steps[0].output["outcome"] == "unknown"
        assert stored.steps[0].output["retryable"] is False
        assert queue.get(run.run_id).state == "unknown"
        assert not queue.get(run.run_id).finished_at
        assert queue.claim("replacement", lease_seconds=60) is None
        service = AgentOrchestrator(
            repository=repository, tool_executor=_ExitingCheckpointExecutor()
        )
        assert (
            service.execute_dispatched_run(run.run_id, recovered=True).to_dict() == stored.to_dict()
        )
        with sqlite3.connect(fixture) as db:
            assert db.execute("select file from elt_checkpoint_test").fetchall() == [(1,)]
        return
    assert stored.status == "running", (stored.steps[0].status, stored.steps[0].output)
    with sqlite3.connect(marker_db) as db:
        owner, inflight = db.execute("select owner, inflight from tool_idempotency").fetchone()
        assert ":elt-lease-v1:" in owner and inflight == 1
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(fixture) as db:
        db.execute(
            "update agent_task_executions set lease_expires_at=? where run_id=?",
            (expired, run.run_id),
        )
    new = queue.claim("replacement", lease_seconds=60)
    assert new.run_id == old.run_id and new.execution_count == old.execution_count + 1
    dispatcher._execute_claim(new, "replacement")
    stored = repository.get(run.run_id)
    # cleanup_verified refers to reaping the exited process, not import-result
    # verification. The synthetic table below proves exact-once fixture writes;
    # its bare count cannot certify a real ELT business result.
    assert stored.status == "blocked" and queue.get(run.run_id).state == "unknown"
    assert stored.tool_calls[-1].metadata["verification"]["code"] == "result_verifier_unavailable"
    assert queue.get(run.run_id).last_error_code == "needs_verification"
    assert not queue.get(run.run_id).finished_at
    assert stored.tool_calls[-1].output == stored.steps[0].output
    assert queue.claim("third-worker", lease_seconds=60, run_id=run.run_id) is None
    with pytest.raises(ValueError, match="人工核对"):
        AgentOrchestrator(repository=repository).retry_run(run.run_id)
    _assert_unverified_not_replayable(repository, queue, stored, actor)
    assert stored.steps[0].output == {"success": True, "data": {"executed_rows": 2}}
    assert stored.metadata["verification"]["steps"][0]["code"] == "result_verifier_unavailable"
    with sqlite3.connect(fixture) as db:
        assert db.execute("select file from elt_checkpoint_test order by file").fetchall() == [
            (1,),
            (2,),
        ]


@pytest.mark.parametrize("business_status", [None, "failed"])
def test_concurrent_retry_preserves_original_write_receipt_and_atomically_requeues_same_run(
    trusted_actor, monkeypatch, business_status
):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = _run(actor, status="failed", completed_write=True)
    if business_status:
        run.steps[0].output["data"] = {"id": 81, "status": business_status}
    original = repository.save(run)
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

    stored = _finish_with_startup(
        monkeypatch,
        repository,
        queue,
        execute,
        original.run_id,
        expected_status="blocked",
        expected_queue_state="unknown",
    )
    _assert_unverified_not_replayable(repository, queue, stored, actor)
    assert (
        stored.metadata["verification"]["steps"][0]["code"]
        == "historical_receipt_has_no_verification_contract"
    )
    assert stored.steps[0].to_dict() == before
    assert calls == [
        ("second", task_execution_context(original, original.steps[1])["idempotency_key"])
    ]


@pytest.mark.parametrize(
    "condition",
    [
        "unknown",
        "nested_unknown",
        "nested_timeout",
        "completed_unknown",
        "completed_failure",
        "completed_not_ok",
        "completed_failed_status",
        "completed_failed_verification",
        "completed_unverified",
        "plan_changed",
        "write_pending",
        "live_lease",
    ],
)
def test_retry_rejects_unverified_original_state_without_queue_changes(trusted_actor, condition):
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = _run(actor, status="failed", completed_write=True)
    if condition == "unknown":
        run.steps[1].output = {"success": False, "outcome": "unknown"}
    elif condition in {"nested_unknown", "nested_timeout"}:
        run.steps[1].output = {
            "success": True,
            "result": {
                "execution_status": "unknown" if condition == "nested_unknown" else "timeout"
            },
        }
    elif condition.startswith("completed_"):
        child = {
            "completed_unknown": {"outcome_unknown": True},
            "completed_failure": {"success": False},
            "completed_not_ok": {"ok": False},
            "completed_failed_status": {"success": True, "execution_status": "failed"},
            "completed_failed_verification": {"success": True, "verification": {"accepted": False}},
            "completed_unverified": {"success": True, "verification": {"status": "inconclusive"}},
        }[condition]
        run.steps[0].output["result"] = {"outputs": [{"output": child}]}
    elif condition == "plan_changed":
        run.steps[1].params["id"] = 3
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


@pytest.mark.parametrize("verified", [False, True])
def test_original_write_receipt_settles_open_effect_before_another_worker_takes_lease(
    trusted_actor, monkeypatch, verified
):
    from tests.fixtures.verified_effect import attach_fixture_verified_write

    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    run = _run(actor, status="running", completed_write=True)
    if verified:
        attach_fixture_verified_write(run, monkeypatch)
    repository.save(run)
    queue.enqueue(run)
    assert queue.claim("dead-worker", lease_seconds=60)
    queue.mark_open_effect(run.run_id, run.steps[0].step_id)
    future = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
    claimed = queue.claim("replacement", lease_seconds=60, now=future)
    if verified:
        assert claimed is not None and claimed.lease_owner == "replacement"
        assert queue.lifecycle(run.run_id)["effects"] == []
    else:
        assert claimed is None
        assert queue.get(run.run_id).state == "unknown"
        assert queue.lifecycle(run.run_id)["effects"] == [run.steps[0].step_id]
    assert repository.get(run.run_id).steps[0].output == run.steps[0].output
    assert repository.get(run.run_id).status == "running"


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
    plan.nodes[1].params["id"] = 3
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
    assert stored.status == "blocked" and stored.error == "计划图校验或执行失败"
    rejected = [event for event in stored.events if event.event_type == "workflow.graph_rejected"]
    assert len(rejected) == 1 and rejected[0].message == stored.error
    assert rejected[0].data["run_id"] == run.run_id
    assert "任务检查点版本不受支持" not in json.dumps(stored.to_dict(), ensure_ascii=False)
    assert stored.tool_calls == [] and all(step.status == "pending" for step in stored.steps)
    assert service.execute_dispatched_run(run.run_id, recovered=True).to_dict() == stored.to_dict()
    assert repository.get(run.run_id).metadata["checkpoint"] == {
        "backend": "langgraph",
        "schema_version": 999,
    }
    assert calls == []


@pytest.fixture(params=["sqlite", "postgres"])
def receipt_fence_repositories(request, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    admin = None
    schema = "receipt_fence_" + uuid.uuid4().hex
    if request.param == "postgres":
        url = os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL")
        if not url:
            pytest.skip("requires CI PostgreSQL service")
        admin = create_engine(url)
        with admin.begin() as db:
            db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'receipt-fence.db'}")
    factory = sessionmaker(bind=engine)
    repository = SQLAlchemyAgentRunRepository(session_factory=factory)
    repository._ensure_schema()
    try:
        yield repository, SQLAlchemyAgentRunRepository(session_factory=factory, auto_create=False)
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as db:
                db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()


@pytest.mark.parametrize("terminal", ["completed", "blocked"])
@pytest.mark.parametrize("context_change", ["untrusted_sources", "session_row_id"])
def test_late_context_update_cannot_erase_terminal_or_unknown_receipt(
    receipt_fence_repositories, terminal, context_change
):
    repository, late_writer = receipt_fence_repositories
    run = AgentRun(user_id="receipt-owner", message="original request", status="running")
    run.metadata["task_context"] = {"task_id": "receipt-task", "attempt": 1}
    run.metadata["runtime_context"] = {
        "tenant_id": "receipt-tenant",
        "_mod_authorization": {"mod_id": "receipt-mod"},
        "_actor_authorization": {"user_id": "receipt-owner", "session_row_id": 1},
    }
    repository.save(run)
    stale = late_writer.get(run.run_id)
    stale.final_output = {"answer": "stale"}
    if context_change == "untrusted_sources":
        stale.metadata["runtime_context"][context_change] = [
            {"source": "tool_output", "text": "observation"}
        ]
    else:
        stale.metadata["runtime_context"]["_actor_authorization"][context_change] = 2
    terminal_committed = threading.Event()

    def save_late():
        assert terminal_committed.wait(10)
        return late_writer.save(stale)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(save_late)
        run.status = terminal
        run.final_output = {"answer": "authoritative"}
        if terminal == "blocked":
            run.metadata.update(
                non_retryable=True, recovery={"state": "manual_reconciliation_required"}
            )
        try:
            repository.save(run)
        finally:
            terminal_committed.set()
        assert result.result(timeout=10).status == terminal
    saved = repository.get(run.run_id)
    assert saved.status == terminal
    assert saved.final_output["answer"] == "authoritative"
    task = repository.get_task(
        user_id=run.user_id, task_id="receipt-task", tenant_id="receipt-tenant"
    )
    assert (task.active_run_id, task.status, task.attempt) == (run.run_id, terminal, 1)
    if terminal == "blocked":
        assert saved.metadata["non_retryable"] is True
        assert saved.metadata["recovery"]["state"] == "manual_reconciliation_required"


@pytest.mark.parametrize("changed", ["user_id", "tenant_id", "mod_id"])
def test_existing_run_identity_cannot_change_with_context(receipt_fence_repositories, changed):
    repository, late_writer = receipt_fence_repositories
    run = AgentRun(user_id="original-owner", message="bound request", status="running")
    run.metadata["runtime_context"] = {
        "tenant_id": "original-tenant",
        "_mod_authorization": {"mod_id": "original-mod"},
    }
    repository.save(run)
    original = repository.get(run.run_id).to_dict()
    modified = late_writer.get(run.run_id)
    if changed == "user_id":
        modified.user_id = "other-owner"
    elif changed == "tenant_id":
        modified.metadata["runtime_context"]["tenant_id"] = "other-tenant"
    else:
        modified.metadata["runtime_context"]["_mod_authorization"]["mod_id"] = "other-mod"
    with pytest.raises(ValueError, match="run identity"):
        late_writer.save(modified)
    assert repository.get(run.run_id).to_dict() == original


@pytest.mark.skipif(
    not os.environ.get("XCAGI_TEST_AGENT_POSTGRES_URL"), reason="requires CI PostgreSQL service"
)
@pytest.mark.parametrize("entrypoint", ["continue", "active"])
@pytest.mark.parametrize("present", [False, True])
def test_postgres_batch_scope_filters_history_and_keeps_legacy_payloads(
    monkeypatch, entrypoint, present
):
    import uuid

    from sqlalchemy import create_engine

    from tests.test_application.test_elt_batch_continuation import _assert_batch_scope_lookup

    url = os.environ["XCAGI_TEST_AGENT_POSTGRES_URL"]
    admin = create_engine(url)
    schema = "batch_scope_" + uuid.uuid4().hex
    with admin.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        _assert_batch_scope_lookup(monkeypatch, engine, entrypoint, present)
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


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
