"""Process death, durable native checkpoints and safe same-task continuation."""

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


class _ExitingCheckpointExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        from app.application.agent_orchestrator.business_write_guard import (
            capture_worker_claim,
            owns_elt_step,
        )
        from app.application.agent_orchestrator.tool_permission import (
            begin_idempotent_replay,
            finish_idempotent_replay,
        )

        assert owns_elt_step(runtime_context) and runtime_context["durable_elt_batch"] is True
        key, replay = begin_idempotent_replay(
            runtime_context, step.tool_id, step.action, step.params
        )
        assert replay is None, replay
        fixture = os.environ["DATABASE_URL"].removeprefix("sqlite:///")
        if capture_worker_claim()[2] == 1:
            with sqlite3.connect(fixture) as db:
                db.execute("insert into elt_checkpoint_test values (1)")
            os._exit(23)
        with sqlite3.connect(fixture) as db:
            assert db.execute("select file from elt_checkpoint_test").fetchall() == [(1,)]
            db.execute("insert into elt_checkpoint_test values (2)")
        result = {"success": True, "data": {"executed_rows": 2}}
        finish_idempotent_replay(key, result)
        return result


def _run(actor, *, status="queued", completed_write=False):
    first = WorkflowNode(
        node_id="first",
        tool_id="business_db",
        action="read",
        params={"entity": "customers", "id": 1},
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
                tool_id="business_db",
                action="read",
                params={"entity": "customers", "id": 2},
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
    context = {**actor.context, "conversation_id": task_id, "workspace_id": task_id}
    run.metadata.update(
        runtime_context=context,
        execution_authorization_scope=authorization_scope_hash(context),
        plan=plan_to_dict(plan),
        task_context={"task_id": task_id},
        task_request={"tool_id": first.tool_id, "action": first.action},
    )
    if completed_write:
        # A historical execution receipt is retained, but has no independent
        # business evidence and must never make the resumed task successful.
        run.steps[0].status = "completed"
        run.steps[0].output = {"success": True, "quote_id": 81}
        run.steps[1].status = "failed"
    return run


def _repositories(actor):
    return (
        SQLAlchemyAgentRunRepository(session_factory=actor.factory),
        SQLAlchemyTaskExecutionRepository(session_factory=actor.factory),
    )


def _finish_with_startup(
    monkeypatch,
    repository,
    queue,
    execute,
    run_id,
    *,
    expected_status="completed",
    expected_queue_state=None,
):
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
        assert stored.status == expected_status, stored.to_dict()
        assert queue.get(run_id).state == (
            expected_queue_state
            or ("succeeded" if expected_status == "completed" else expected_status)
        )
        return stored
    finally:
        dispatcher.stop()
        set_agent_run_repository_for_tests(None)


def _assert_unverified_not_replayable(repository, queue, run, actor):
    assert run.status == "blocked"
    assert queue.get(run.run_id).state == "unknown"
    assert run.metadata["verification"]["accepted"] is False
    assert not any(event.event_type == "run.completed" for event in run.events)
    before = repository.get(run.run_id).to_dict()
    execution = queue.get(run.run_id).to_dict()
    future = (datetime.now(UTC) + timedelta(seconds=120)).isoformat()
    assert queue.claim("unexpected-replay", lease_seconds=60, now=future) is None
    with pytest.raises(ValueError, match="核对"):
        AgentOrchestrator(repository=repository).retry_run(
            run.run_id,
            requested_by=str(actor.user_id),
            auto_execute=False,
            authenticated_binding=actor.principal.mod_authorization,
        )
    assert repository.get(run.run_id).to_dict() == before
    assert queue.get(run.run_id).to_dict() == execution


def test_real_executor_resumes_crashed_read_claim_under_replacement_queue_lease(
    trusted_actor, tmp_path, monkeypatch
):
    from app.application.agent_orchestrator import tool_permission
    from app.db.models.purchase_unit import PurchaseUnit

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(role="admin")
    with actor.factory.begin() as db:
        db.add_all(
            PurchaseUnit(id=index, tenant_id=actor.tenant_id, unit_name=f"customer-{index}")
            for index in (1, 2)
        )
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
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(Path(__file__).resolve().parents[2]), env.get("PYTHONPATH", "")))
    )
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
        assert [step.output["data"][0]["unit_name"] for step in stored.steps] == [
            "customer-1",
            "customer-2",
        ]
        for step in stored.steps:
            row = step.output["data"][0]
            assert row["tenant_id"] == actor.tenant_id
            for field in ("created_at", "updated_at"):
                assert isinstance(row[field], str) and datetime.fromisoformat(row[field])
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
                context, "business_db", "read", params
            )
            assert replay is None
            assert (
                tool_permission.begin_idempotent_replay(context, "business_db", "read", params)[1][
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
                context, "business_db", "read", params
            ) == (key, None)
        with worker_claim_scope(repository, first, first.lease_owner):
            with pytest.raises(WorkerLeaseLost):
                tool_permission.begin_idempotent_replay(context, "business_db", "read", params)
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


@pytest.mark.parametrize("open_effect", [False, True])
@pytest.mark.parametrize("approval_source", ["grant", "workspace", "workspace_legacy"])
def test_restart_preserves_exact_queued_approval_before_first_write(
    trusted_actor, monkeypatch, open_effect, approval_source
):
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.stale_run_reconciler import reconcile_stale_running_runs
    from app.application.workflow.approval_persistence import (
        claim_agent_approval,
        persist_agent_run_link,
        persist_workflow_approval,
    )
    from app.application.workflow.workflow_types import ApprovalRequest, ApprovalStatus
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    actor = trusted_actor(role="admin")
    repository, queue = _repositories(actor)
    node = WorkflowNode(
        "import",
        "elt_import",
        "execute",
        {"file_paths": ["648777a2-83cb-4b1d-b20f-8370b498032b"]},
        risk="high",
    )
    plan = PlanGraph("queued-import", "导入", nodes=[node])
    plan.metadata["approval_required_node_ids"] = [node.node_id]
    if approval_source != "grant":
        plan.metadata["durable_elt_batch"] = True
    legacy = approval_source == "workspace_legacy"
    parent = None
    if legacy:
        parent = repository.save(AgentRun(str(actor.user_id), "原导入", status="blocked"))
        plan.plan_id = f"continue-{parent.run_id}"
        plan.metadata.update(
            source="elt_batch_continuation",
            continued_from_run_id=parent.run_id,
            legacy_elt_tail_recheck=True,
        )
    step = AgentOrchestrator._step_from_node(node)
    step.status = "waiting_user"
    step.risk = "high"
    node.idempotent = step.idempotent
    run = AgentRun(
        user_id=str(actor.user_id),
        message=plan.intent,
        status="waiting_user",
        plan_id=plan.plan_id,
        steps=[step],
    )
    run.metadata.update(
        plan=plan_to_dict(plan),
        runtime_context=actor.context,
        execution_authorization_scope=authorization_scope_hash(actor.context),
    )
    if parent is not None:
        run.metadata["task_context"] = {
            "task_id": parent.run_id,
            "parent_run_id": parent.run_id,
            "root_run_id": parent.run_id,
            "attempt": 2,
        }
    repository.save(run)
    queue.get(run.run_id)
    if approval_source != "grant":
        request = ApprovalRequest(
            "workspace-task",
            plan.plan_id,
            node.node_id,
            node.tool_id,
            node.action,
            node.params,
            ApprovalStatus.PENDING,
            datetime.now(UTC),
            tenant_id=actor.tenant_id,
        )
        monkeypatch.setattr(
            "app.application.agent_orchestrator.task_execution_repository.get_task_execution_repository",
            lambda: queue,
        )
        notified = []
        monkeypatch.setattr(
            task_dispatcher, "notify_agent_task_dispatcher", lambda: notified.append(1)
        )
        service = AgentOrchestrator(repository=repository)
        args = {
            "approved_by": run.user_id,
            "approved_step_id": step.step_id,
            "approval_request_id": request.request_id,
        }
        with tenant_scope(actor.tenant_id):
            assert persist_workflow_approval(
                request, actor.context, flow_key="import-test", plan=plan
            )
            assert persist_agent_run_link(
                request.request_id, agent_run_id=run.run_id, approved_step_id=step.step_id
            )
            assert service.continue_run(run.run_id, **args) is None
            assert (
                repository.get(run.run_id).status == "waiting_user"
                and queue.get(run.run_id) is None
            )
            assert claim_agent_approval(
                request.request_id, agent_run_id=run.run_id, approved_step_id=step.step_id
            )
            if parent is not None:
                lineage = {
                    "task_id": parent.run_id,
                    "root_run_id": parent.run_id,
                    "task_attempt": 2,
                }
                checked = []
                pinned = copy.deepcopy(plan)

                def readback(source, context):
                    checked.append(source.run_id)
                    assert context["_actor_authorization"] == actor.context["_actor_authorization"]
                    return pinned, lineage

                monkeypatch.setattr(
                    "app.application.elt.batch_continuation.build_legacy_batch_continuation",
                    readback,
                )
                pinned.nodes[0].params["file_paths"] = ["648777a2-83cb-4b1d-b20f-8370b498032c"]
                assert service.continue_run(run.run_id, **args) is None
                assert repository.get(run.run_id).status == "waiting_user"
                assert queue.get(run.run_id) is None and notified == []
                pinned.nodes[0].params["file_paths"] = node.params["file_paths"]
            approved = service.continue_run(run.run_id, **args)
            if parent is not None:
                assert checked == [parent.run_id, parent.run_id]
        assert notified == [1]
        assert approved.metadata["approval_receipt"]["queue_approval"] == "workspace_claim"
    else:
        grant = issue_approval_grant(run, principal_id=run.user_id)
        approved = approve_and_enqueue(
            repository,
            queue,
            run_id=run.run_id,
            token=grant["grant"],
            principal_id=run.user_id,
            runtime_context={},
        )
    assert approved.status == queue.get(run.run_id).state == "queued"
    assert approved.metadata["approval_receipt"]["step_id"] == step.step_id
    assert "grant" not in approved.metadata["approval_receipt"]

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import SQLAlchemyTaskExecutionRepository
factory = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))
repo = SQLAlchemyAgentRunRepository(session_factory=factory)
queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
run = repo.get(sys.argv[1])
claim = queue.claim("crashed", lease_seconds=60)
assert claim.run_id == run.run_id
run.status = run.metadata["dispatch"]["state"] = "running"
if sys.argv[2] == "True":
    run.steps[0].status = "running"
    assert queue.mark_open_effect(
        run.run_id, run.steps[0].step_id,
        owner_id=claim.lease_owner, execution_count=claim.execution_count)
repo.save(run)
os._exit(23)
""",
            run.run_id,
            str(open_effect),
        ],
        timeout=25,
        capture_output=True,
    )
    assert child.returncode == 23, child.stderr.decode()

    if open_effect and approval_source == "grant":
        set_agent_run_repository_for_tests(repository)
        try:
            assert reconcile_stale_running_runs() == 1
            stored = repository.get(run.run_id)
            assert stored.metadata["recovery"]["step_ids"] == [step.step_id]
            assert stored.metadata["recovery"]["state"] == "manual_reconciliation_required"
            assert queue.claim("replacement", lease_seconds=60) is None
        finally:
            set_agent_run_repository_for_tests(None)
        return

    calls = []

    def execute(resumed_step, *, runtime_context):
        calls.append((resumed_step.step_id, runtime_context["idempotency_key"]))
        if open_effect:
            return {"success": False, "outcome": "unknown", "reconciliation_required": True}
        return {"success": True, "data": {"executed_rows": 1}}

    if open_effect:
        set_agent_run_repository_for_tests(repository)
        try:
            assert reconcile_stale_running_runs() == 1
            claimed = queue.claim("replacement", lease_seconds=60)
            dispatcher = task_dispatcher.AgentTaskDispatcher(
                execution_repository=queue,
                run_repository=repository,
                orchestrator_factory=lambda repo: AgentOrchestrator(
                    repository=repo,
                    tool_executor=SimpleNamespace(execute=execute),
                ),
            )
            dispatcher._execute_claim(claimed, "replacement")
            assert queue.claim("second-replacement", lease_seconds=60) is None
            stored = repository.get(run.run_id)
            assert stored.metadata["recovery"]["state"] == "manual_reconciliation_required"
        finally:
            set_agent_run_repository_for_tests(None)
    else:
        stored = _finish_with_startup(
            monkeypatch,
            repository,
            queue,
            execute,
            run.run_id,
            expected_status="blocked",
            expected_queue_state="unknown",
        )
        _assert_unverified_not_replayable(repository, queue, stored, actor)
        assert stored.steps[0].output == {"success": True, "data": {"executed_rows": 1}}
        assert (
            stored.tool_calls[-1].metadata["verification"]["code"] == "result_verifier_unavailable"
        )
        assert stored.tool_calls[-1].output == stored.steps[0].output
        assert queue.get(run.run_id).last_error_code == "needs_verification"
        assert not queue.get(run.run_id).finished_at
        assert queue.claim("another-replacement", lease_seconds=60, run_id=run.run_id) is None
        with pytest.raises(ValueError, match="人工核对"):
            AgentOrchestrator(repository=repository).retry_run(run.run_id)
    assert (
        approved.metadata["approval_receipt"].items() <= stored.metadata["approval_receipt"].items()
    )
    assert calls == [(step.step_id, task_execution_context(run, step)["idempotency_key"])]
    assert queue.get(run.run_id).execution_count == 2
