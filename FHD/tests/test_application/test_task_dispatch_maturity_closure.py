"""Exercise admission, fair SQL claims and bounded reads on the original queue."""

from __future__ import annotations

import multiprocessing
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
import pytest
from sqlalchemy import text

from app.application.agent_orchestrator import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.task_execution_models import TaskQueueCapacityError
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.task_dispatch_maturity_workers import native_queue_client
from tests.test_application.test_agent_task_admission import (
    admission_sessions as admission_sessions,
)


@pytest.fixture(autouse=True)
def queue_limits(monkeypatch):
    for name, value in {
        "MAX_ADMITTED": 64,
        "TENANT_MAX_ADMITTED": 32,
        "MAX_INFLIGHT": 4,
        "TENANT_MAX_INFLIGHT": 3,
        "INTERACTIVE_SECONDS": 4,
        "AGING_SECONDS": 30,
    }.items():
        monkeypatch.setenv("XCAGI_AGENT_TASK_" + name, str(value))


def _run(tenant: str, label: str, *, read: bool = False) -> AgentRun:
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    run = AgentRun(user_id="owner-" + tenant, message=label, status="queued")
    run.metadata["runtime_context"] = {"tenant_id": tenant}
    run.metadata["task_context"] = {"task_id": label}
    run.steps = [
        AgentStep(
            node_id="query",
            tool_id="business_db",
            action="read",
            params={"entity": "customers", "keyword": label},
            idempotent=True,
        )
    ]
    if not read:
        run.steps.append(AgentStep(node_id="followup", tool_id="business_db", action="read"))
    run.metadata["plan"] = plan_to_dict(
        PlanGraph(
            plan_id=label,
            intent="query",
            nodes=[
                WorkflowNode(
                    node_id=step.node_id,
                    tool_id=step.tool_id,
                    action=step.action,
                    params=dict(step.params),
                )
                for step in run.steps
            ],
        )
    )
    return run


@pytest.fixture
def queue_stack(admission_sessions):
    # Catalog discovery is deliberately outside every queue/run transaction.
    build_tool_specs_v2()
    repository = SQLAlchemyAgentRunRepository(session_factory=admission_sessions)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=admission_sessions)
    repository._ensure_schema()
    queue._ensure_schema()
    return repository, queue


def _enqueue(stack, run, **kwargs):
    repository, queue = stack
    repository.save(run)
    return queue.enqueue(run, **kwargs)


@pytest.mark.parametrize("scope", ["global", "tenant"])
def test_capacity_refusal_preserves_original_idempotency_and_does_not_consume_new_key(
    queue_stack,
    monkeypatch,
    scope,
):
    monkeypatch.setenv(
        "XCAGI_AGENT_TASK_MAX_ADMITTED"
        if scope == "global"
        else "XCAGI_AGENT_TASK_TENANT_MAX_ADMITTED",
        "1",
    )
    _, queue = queue_stack
    first = _run("a", "first")
    _enqueue(queue_stack, first, idempotency_key="first", fingerprint="same")
    duplicate = _run("a", "duplicate")
    assert (
        queue.enqueue(duplicate, idempotency_key="first", fingerprint="same").run_id == first.run_id
    )
    second = _run("a", "second")
    with pytest.raises(TaskQueueCapacityError) as error:
        _enqueue(queue_stack, second, idempotency_key="second", fingerprint="same")
    assert error.value.scope == scope
    assert queue.get(second.run_id) is None
    assert queue.transition(first.run_id, "cancelled").state == "cancelled"
    assert (
        queue.enqueue(second, idempotency_key="second", fingerprint="same").run_id == second.run_id
    )


def test_memory_admission_rejection_does_not_poison_idempotency(monkeypatch):
    monkeypatch.setenv("XCAGI_AGENT_TASK_MAX_ADMITTED", "1")
    queue = InMemoryTaskExecutionRepository()
    first, second = _run("a", "first"), _run("b", "second")
    queue.enqueue(first, idempotency_key="first")
    with pytest.raises(TaskQueueCapacityError):
        queue.enqueue(second, idempotency_key="second")
    assert ("agent", "b", "second") not in queue._book.idem
    queue.transition(first.run_id, "cancelled")
    assert queue.enqueue(second, idempotency_key="second").run_id == second.run_id


def test_tenant_fairness_and_reserved_read_slot_survive_a_large_background_prefix(queue_stack):
    _, queue = queue_stack
    burst = [_run("a", f"long-a-{index}") for index in range(12)]
    for run in burst:
        _enqueue(queue_stack, run, priority=-100)
    other = _run("b", "long-b")
    _enqueue(queue_stack, other, priority=100)
    claims = [queue.claim(f"worker-{index}", lease_seconds=120) for index in range(3)]
    assert [claim.tenant_id for claim in claims] == ["a", "b", "a"]
    assert queue.claim("fourth-background", lease_seconds=120) is None
    read = _run("a", "short-read", read=True)
    admitted = _enqueue(queue_stack, read, priority=999)
    assert admitted.dispatch_class == "interactive" and admitted.dispatch_deadline_seconds == 4
    selected = queue.claim("bounded-reader", lease_seconds=120)
    assert selected.run_id == read.run_id and selected.dispatch_class == "interactive"
    assert queue.claim("over-global-limit", lease_seconds=120) is None


def test_old_low_priority_work_ages_ahead_of_new_priority_work(queue_stack, admission_sessions):
    from app.db.models.agent import AgentTaskExecutionRecord

    _, queue = queue_stack
    old, new = _run("a", "old"), _run("a", "new")
    _enqueue(queue_stack, old, priority=1000)
    _enqueue(queue_stack, new, priority=-1000)
    with admission_sessions.begin() as db:
        row = db.get(AgentTaskExecutionRecord, old.run_id)
        row.available_at = (datetime.now(UTC) - timedelta(seconds=31)).isoformat()
    assert queue.claim("aged-worker", lease_seconds=120).run_id == old.run_id


@pytest.mark.parametrize("mutation", ["params", "plan", "contract", "caller_hint", "cold_catalog"])
def test_interactive_capacity_is_frozen_from_host_state_and_rechecked_without_discovery(
    queue_stack,
    admission_sessions,
    monkeypatch,
    mutation,
):
    import json
    from dataclasses import replace

    from app.application.agent_orchestrator import tool_spec
    from app.db.models.agent import AgentRunRecord
    from app.domain.task_lifecycle.control import SessionBook

    _, queue = queue_stack
    read = _run("a", "trusted-read", read=mutation != "caller_hint")
    read.metadata["dispatch_policy"] = {"class": "interactive", "deadline_seconds": 1}

    def discovery_is_forbidden(*_args, **_kwargs):
        raise AssertionError("queue admission/claim must not refresh a remote catalog")

    monkeypatch.setattr(tool_spec, "build_tool_specs_v2", discovery_is_forbidden)
    if mutation == "cold_catalog":
        monkeypatch.setattr(tool_spec, "_TOOL_SPECS_CACHE", None)
    admitted = _enqueue(queue_stack, read, priority=-99999)
    assert admitted.dispatch_class == (
        "background" if mutation in {"caller_hint", "cold_catalog"} else "interactive"
    )
    if mutation in {"params", "plan"}:
        with admission_sessions.begin() as db:
            row = db.get(AgentRunRecord, read.run_id)
            payload = json.loads(row.payload_json)
            if mutation == "params":
                payload["steps"][0]["params"]["keyword"] = "changed-after-enqueue"
            else:
                payload["metadata"]["plan"]["nodes"].append(
                    {
                        "node_id": "extra",
                        "tool_id": "business_db",
                        "action": "read",
                        "params": {},
                    }
                )
            row.payload_json = json.dumps(payload)
    elif mutation == "contract":
        snapshot = tool_spec.snapshot_tool_specs_v2()
        snapshot[("business_db", "read")] = replace(
            snapshot[("business_db", "read")],
            read_only=False,
        )
        monkeypatch.setattr(tool_spec, "_TOOL_SPECS_CACHE", snapshot)
    assert queue.claim("reserved-slot", lease_seconds=120, interactive_only=True) is None
    claimed = queue.claim("ordinary-slot", lease_seconds=120)
    assert claimed.run_id == read.run_id and claimed.dispatch_class == "background"
    with admission_sessions() as db:
        assert SessionBook(db).get("agent", "a", read.run_id)["dispatch_policy"] == {
            "class": "background"
        }


@pytest.mark.parametrize("mode", ["admit-global", "admit-tenant", "claim-tenant"])
def test_independent_processes_cannot_exceed_admission_or_tenant_running_quotas(
    queue_stack,
    admission_sessions,
    monkeypatch,
    mode,
):
    _, queue = queue_stack
    if mode.startswith("admit"):
        name = "MAX_ADMITTED" if mode == "admit-global" else "TENANT_MAX_ADMITTED"
        monkeypatch.setenv("XCAGI_AGENT_TASK_" + name, "2")
    else:
        monkeypatch.setenv("XCAGI_AGENT_TASK_TENANT_MAX_INFLIGHT", "1")
        for index in range(4):
            _enqueue(queue_stack, _run("shared", f"queued-{index}"))
    engine = admission_sessions.kw["bind"]
    options = {}
    if engine.dialect.name == "postgresql":
        with admission_sessions() as db:
            options = {"options": "-csearch_path=" + db.scalar(text("SELECT current_schema()"))}
    url = engine.url.render_as_string(hide_password=False)
    ctx = multiprocessing.get_context("spawn")
    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [
        ctx.Process(
            target=native_queue_client, args=(url, options, mode, index, ready, start, results)
        )
        for index in range(4)
    ]
    try:
        for process in processes:
            process.start()
        assert {ready.get(timeout=40) for _ in processes} == set(range(4))
        start.set()
        returned = [results.get(timeout=25) for _ in processes]
        assert sum(item is not None for item in returned) == (1 if mode == "claim-tenant" else 2)
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


class HangingReadExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        Path(step.params["keyword"]).write_text(str(os.getpid()))
        time.sleep(30)
        return {"success": True, "data": []}


def test_reserved_read_deadline_reaps_real_process_and_releases_queue_slot(
    trusted_actor, tmp_path, monkeypatch
):
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from tests.test_application.test_task_dispatcher import _orchestrator_factory, _queued_run

    monkeypatch.setenv("XCAGI_AGENT_TASK_INTERACTIVE_SECONDS", "8")
    actor = trusted_actor()
    build_tool_specs_v2()
    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    marker = tmp_path / "worker-started"
    run = _queued_run(actor, str(marker))
    repository.save(run)
    queue.enqueue(run)
    execution = queue.claim("bounded-worker", lease_seconds=120)
    assert execution.dispatch_class == "interactive" and execution.dispatch_deadline_seconds == 8
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda repo: _orchestrator_factory(repo, HangingReadExecutor()),
    )
    dispatcher._execute_claim(execution, "bounded-worker")
    assert time.monotonic() - started < 12
    stored = repository.get(run.run_id)
    assert marker.exists(), (stored.error, [step.output for step in stored.steps])
    assert not psutil.pid_exists(int(marker.read_text()))
    assert {child.pid for child in multiprocessing.active_children()} <= before
    assert queue.get(run.run_id).state == "unknown"
    assert queue.claim("must-not-replay", lease_seconds=120) is None
