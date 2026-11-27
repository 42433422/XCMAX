from __future__ import annotations

import threading
import time

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def actor(trusted_actor):
    return trusted_actor()


def _queued_run(actor, task_id: str, *, idempotent: bool = True) -> AgentRun:
    run = AgentRun(user_id=str(actor.user_id), message=task_id, status="queued")
    run.metadata["runtime_context"] = dict(actor.context)
    run.metadata["task_context"] = {"task_id": task_id, "attempt": 1}
    run.steps.append(
        AgentStep(
            node_id="query",
            tool_id="business_db",
            action="read",
            params={"entity": "customers", "keyword": task_id},
            risk="low" if idempotent else "high",
            idempotent=idempotent,
        )
    )
    run.metadata["plan"] = plan_to_dict(
        PlanGraph(
            plan_id=task_id,
            intent="customers_query",
            nodes=[
                WorkflowNode(
                    node_id="query",
                    tool_id="business_db",
                    action="read",
                    params={"entity": "customers", "keyword": task_id},
                    risk="low",
                    idempotent=True,
                )
            ],
        )
    )
    return run


def _orchestrator_factory(repository, executor):
    orchestrator = AgentOrchestrator(repository=repository, tool_executor=executor)
    orchestrator._record_tool_usage_entry = lambda *_args, **_kwargs: True
    return orchestrator


def test_dispatcher_rejects_missing_persisted_plan(actor):
    repository = InMemoryAgentRunRepository()
    executor = _ConcurrentExecutor()
    run = _queued_run(actor, "missing-plan")
    run.metadata.pop("plan")
    repository.save(run)
    blocked = _orchestrator_factory(repository, executor).execute_dispatched_run(run.run_id)
    assert blocked.status == "blocked"
    assert "计划图缺失" in blocked.error
    assert executor.contexts == []


class _ConcurrentExecutor:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.two_started = threading.Event()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.contexts: list[dict[str, object]] = []

    def execute(self, _step, *, runtime_context):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.contexts.append(dict(runtime_context))
            if self.active == 2:
                self.two_started.set()
        self.release.wait(timeout=3)
        with self._lock:
            self.active -= 1
        return {"success": True, "data": []}


def _wait_until(predicate, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_dispatcher_runs_two_tasks_concurrently_with_stable_idempotency_keys(actor) -> None:
    run_repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    executor = _ConcurrentExecutor()
    runs = [_queued_run(actor, "task-one"), _queued_run(actor, "task-two")]
    for run in runs:
        run_repository.save(run)
        queue.enqueue(run, requested_by=str(actor.user_id))
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=run_repository,
        max_workers=2,
        poll_seconds=0.02,
        orchestrator_factory=lambda repository: _orchestrator_factory(repository, executor),
    )

    dispatcher.start()
    try:
        assert executor.two_started.wait(timeout=3)
        assert dispatcher.snapshot()["active_count"] == 2
        executor.release.set()
        assert _wait_until(
            lambda: all(
                (run_repository.get(run.run_id) or run).status == "completed" for run in runs
            )
        )
    finally:
        executor.release.set()
        dispatcher.stop()

    assert executor.max_active == 2
    assert {str(context["task_id"]) for context in executor.contexts} == {
        "task-one",
        "task-two",
    }
    assert all(
        str(context["idempotency_key"]).startswith("agent:run_") for context in executor.contexts
    )
    assert all(queue.get(run.run_id).state == "succeeded" for run in runs)  # type: ignore[union-attr]


def test_expired_idempotent_step_recovers_but_non_idempotent_step_fails_closed(actor) -> None:
    repository = InMemoryAgentRunRepository()
    executor = _ConcurrentExecutor()
    executor.release.set()

    idempotent = _queued_run(actor, "recoverable")
    idempotent.status = "running"
    idempotent.steps[0].status = "running"
    idempotent.tool_calls.append(
        ToolCall(
            step_id=idempotent.steps[0].step_id,
            node_id="query",
            tool_id="business_db",
            action="read",
            status="running",
        )
    )
    repository.save(idempotent)
    recovered = _orchestrator_factory(repository, executor).execute_dispatched_run(
        idempotent.run_id,
        recovered=True,
    )

    assert recovered is not None
    assert recovered.status == "completed", recovered.to_dict()
    assert len(recovered.tool_calls) == 2
    assert recovered.tool_calls[0].status == "failed"
    assert recovered.tool_calls[0].error == "worker_lease_expired"
    assert recovered.tool_calls[1].metadata["idempotency_key"].endswith(recovered.steps[0].step_id)

    unsafe = _queued_run(actor, "unsafe", idempotent=False)
    unsafe.status = "running"
    unsafe.steps[0].status = "running"
    repository.save(unsafe)
    calls_before = len(executor.contexts)
    blocked = _orchestrator_factory(repository, executor).execute_dispatched_run(
        unsafe.run_id,
        recovered=True,
    )

    assert blocked is not None
    assert blocked.status == "blocked"
    assert blocked.error == "non_idempotent_recovery_blocked"
    assert blocked.metadata["non_retryable"] is True
    assert blocked.metadata["recovery"]["state"] == "manual_reconciliation_required"
    assert len(executor.contexts) == calls_before


@pytest.mark.parametrize("legacy_claim", [False, True])
def test_quote_recovery_uses_real_registry_and_does_not_replay_unknown_write(legacy_claim, actor):
    from app.application.workflow.workflow_types import WorkflowNode

    repository = InMemoryAgentRunRepository()
    executor = _ConcurrentExecutor()
    executor.release.set()
    orchestrator = _orchestrator_factory(repository, executor)
    run = _queued_run(actor, "unknown-quote")
    run.steps = [
        orchestrator._step_from_node(
            WorkflowNode(
                node_id="quote",
                tool_id="sales",
                action="quote",
                idempotent=True,
                params={
                    "customer_id": 1,
                    "items": [{"product_id": 2, "quantity": 1, "unit_price": 50}],
                },
            )
        )
    ]
    assert run.steps[0].idempotent is False  # Registry overrides planner optimism.
    if legacy_claim:
        run.steps[0].idempotent = True  # Simulate an already persisted pre-fix plan.
    run.status = "running"
    run.steps[0].status = "running"
    repository.save(run)
    recovered = orchestrator.execute_dispatched_run(run.run_id, recovered=True)
    assert recovered.status == "blocked"
    assert recovered.error == "non_idempotent_recovery_blocked"
    assert executor.contexts == []


def test_dispatcher_restart_claims_expired_lease_and_completes_idempotent_task(actor) -> None:
    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    executor = _ConcurrentExecutor()
    executor.release.set()
    run = _queued_run(actor, "restart-recovery")
    run.status = "running"
    run.steps[0].status = "running"
    run.tool_calls.append(
        ToolCall(
            step_id=run.steps[0].step_id,
            node_id="query",
            tool_id="business_db",
            action="read",
            status="running",
        )
    )
    repository.save(run)
    queue.enqueue(run, requested_by=str(actor.user_id))
    assert queue.claim("stopped-process", lease_seconds=0.01) is not None
    time.sleep(1.05)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        max_workers=1,
        poll_seconds=0.02,
        orchestrator_factory=lambda run_repository: _orchestrator_factory(
            run_repository,
            executor,
        ),
    )

    dispatcher.start()
    try:
        assert _wait_until(lambda: (repository.get(run.run_id) or run).status == "completed")
    finally:
        dispatcher.stop()

    execution = queue.get(run.run_id)
    recovered = repository.get(run.run_id)
    assert execution is not None and execution.recovery_count == 1
    assert execution.state == "succeeded"
    assert recovered is not None and len(recovered.tool_calls) == 2
    assert recovered.tool_calls[0].error == "worker_lease_expired"


def test_timeout_unknown_releases_worker_slot_and_prevents_repair_replay(monkeypatch, actor):
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "true")
    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    calls = []

    class DeadlineExecutor:
        def execute_with_deadline(self, step, *, runtime_context, deadline_monotonic):
            assert deadline_monotonic == runtime_context["deadline_monotonic"]
            calls.append(runtime_context["idempotency_key"])
            raise TimeoutError

    runs = [_queued_run(actor, "timeout-one"), _queued_run(actor, "timeout-two")]
    for run in runs:
        run.metadata["repair_overrides"] = {"query": {"retry": True, "max_attempts": 3}}
        repository.save(run)
        queue.enqueue(run)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        max_workers=1,
        poll_seconds=0.02,
        orchestrator_factory=lambda repo: _orchestrator_factory(repo, DeadlineExecutor()),
    )
    dispatcher.start()
    try:
        assert _wait_until(
            lambda: all(
                queue.get(run.run_id).state == "unknown"
                and queue.get(run.run_id).last_error_code == "needs_verification"
                for run in runs
            )
        )
        assert _wait_until(lambda: dispatcher.snapshot()["active_count"] == 0)
        assert len(calls) == 2 and len(set(calls)) == 2
        for run in runs:
            stored = repository.get(run.run_id)
            assert stored.status == "blocked"
            assert stored.metadata["non_retryable"] is True
            assert stored.metadata["recovery"]["state"] == "manual_reconciliation_required"
            assert stored.steps[0].attempt_count == 1
            with pytest.raises(ValueError):
                _orchestrator_factory(repository, DeadlineExecutor()).retry_run(run.run_id)
    finally:
        dispatcher.stop()


@pytest.mark.parametrize("open_effect", [False, True])
def test_worker_assertion_persists_matching_run_task_and_queue(monkeypatch, actor, open_effect):
    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    run = _queued_run(actor, "worker-assertion")
    repository.save(run)
    queue.enqueue(run)
    claim = queue.claim("worker", lease_seconds=30)

    def fail_before_tool(*_args, **_kwargs):
        if open_effect:
            assert queue.mark_open_effect(
                run.run_id, "external", owner_id="worker", execution_count=claim.execution_count
            )
        raise AssertionError("workflow initialization failed")

    monkeypatch.setattr(AgentOrchestrator, "_execute_ready_steps", fail_before_tool)
    AgentTaskDispatcher(execution_repository=queue, run_repository=repository)._execute_claim(
        claim, "worker"
    )
    saved = repository.get(run.run_id)
    task = repository.get_task(user_id=run.user_id, task_id="worker-assertion")
    execution = queue.get(run.run_id)
    assert saved.status == task.status == ("blocked" if open_effect else "failed")
    assert execution.state == ("unknown" if open_effect else "failed")
    assert execution.last_error_code == (
        "needs_verification" if open_effect else "worker_execution_failed"
    )
    assert bool(saved.metadata.get("non_retryable")) is open_effect
    assert not saved.tool_calls
    assert queue.claim("another-worker", lease_seconds=30) is None


@pytest.mark.parametrize(
    "status, tool, output, expected",
    [
        ("paused", "products", {}, "paused"),
        ("blocked", "products", {}, "blocked"),
        ("waiting_user", "clarify", {}, "waiting_input"),
        ("waiting_user", "products", {}, "waiting_approval"),
        ("completed", "products", {"success": True, "pending_approval": True}, "waiting_approval"),
        ("completed", "products", {"success": True, "requires_token": True}, "waiting_auth"),
        ("completed", "products", {"success": True, "outcome_unknown": True}, "unknown"),
        ("running", "products", {}, "unknown"),
    ],
)
def test_worker_yield_preserves_unfinished_receipts(actor, status, tool, output, expected):
    from types import SimpleNamespace

    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    run = _queued_run(actor, "yield-state")
    repository.save(run)
    queue.enqueue(run)
    claim = queue.claim("worker", lease_seconds=30)
    run.status = status
    run.steps[0].tool_id = tool
    run.steps[0].status = "waiting_user" if status == "waiting_user" else status
    run.steps[0].output = output
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda _: SimpleNamespace(
            execute_dispatched_run=lambda *_args, **_kwargs: run
        ),
    )
    dispatcher._execute_claim(claim, "worker")
    stored = queue.get(run.run_id)
    assert stored.state == expected
    assert not stored.finished_at
    assert queue.claim("another-worker", lease_seconds=30) is None


@pytest.mark.parametrize(
    "state",
    ["waiting_approval", "waiting_auth", "waiting_input", "unknown", "timeout", "timed_out"],
)
def test_real_step_preserves_accepted_wait_without_inventing_unknown(actor, state):
    from types import SimpleNamespace

    calls = []
    output = {
        "success": False,
        "execution_state": state,
        "execution_accepted": True,
        "retryable": False,
        "task_id": "original-child",
        "approval_request_id": "original-approval",
    }

    def execute(step, *, runtime_context):
        calls.append(runtime_context["idempotency_key"])
        return dict(output)

    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    run = _queued_run(actor, f"accepted-{state}")
    repository.save(run)
    queue.enqueue(run)
    claim = queue.claim("worker", lease_seconds=30)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda repo: _orchestrator_factory(
            repo, SimpleNamespace(execute=execute)
        ),
    )
    dispatcher._execute_claim(claim, "worker")
    saved = repository.get(run.run_id)
    uncertain = state in {"unknown", "timeout", "timed_out"}
    assert queue.get(run.run_id).state == ("unknown" if uncertain else state)
    assert saved.steps[0].output["execution_state"] == state
    assert saved.steps[0].output["approval_request_id"] == "original-approval"
    assert saved.steps[0].output["task_id"] == "original-child"
    assert bool(saved.steps[0].output.get("reconciliation_required")) is uncertain
    assert (
        saved.metadata.get("recovery", {}).get("state") == "manual_reconciliation_required"
    ) is uncertain
    assert len(calls) == 1
    assert queue.claim("another-worker", lease_seconds=30) is None


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        ({"execution_state": "paused"}, ("paused", "")),
        ({"execution_state": "blocked"}, ("blocked", "")),
        (
            {"execution_state": "blocked", "error_code": "runtime_policy_blocked"},
            ("blocked", "runtime_policy_blocked"),
        ),
        (
            {"execution_state": "blocked", "error_code": "owner_changed"},
            ("blocked", "owner_changed"),
        ),
        ({"execution_state": "waiting_user", "needs_user_input": True}, ("waiting_input", "")),
        ({"execution_state": "waiting_user", "requires_token": True}, ("waiting_auth", "")),
        ({"execution_state": "waiting_user", "pending_approval": True}, ("waiting_approval", "")),
        ({"execution_state": "waiting_input"}, ("waiting_input", "")),
        ({"execution_state": "waiting_auth"}, ("waiting_auth", "")),
        ({"execution_state": "waiting_approval"}, ("waiting_approval", "")),
        ({"execution_state": "running"}, ("waiting_approval", "")),
        ({"execution_state": "cancelled"}, ("cancelled", "")),
        ({"execution_state": "rejected"}, ("rejected", "")),
        ({"execution_state": "unknown"}, ("unknown", "needs_verification")),
        ({"execution_state": "partial"}, ("unknown", "needs_verification")),
        (
            {"execution_state": "blocked", "reconciliation_required": True},
            ("unknown", "needs_verification"),
        ),
        ({"execution_state": "completed", "ok": False}, ("unknown", "needs_verification")),
        (
            {"execution_state": "completed", "ok": True, "reconciliation_required": True},
            ("unknown", "needs_verification"),
        ),
        ({"execution_state": "completed", "ok": True}, ("succeeded", "")),
        ({"execution_state": "failed", "error_code": "model_error"}, ("failed", "model_error")),
        ({"execution_state": "unexpected"}, ("unknown", "needs_verification")),
    ],
)
def test_xiaox_queue_outcome_preserves_receipt_state(receipt, expected):
    from app.application.agent_orchestrator.task_execution_models import xiaox_queue_outcome

    assert xiaox_queue_outcome(receipt) == expected
