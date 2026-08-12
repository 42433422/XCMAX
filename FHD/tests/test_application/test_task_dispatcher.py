from __future__ import annotations

import threading
import time

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
)


def _queued_run(task_id: str, *, idempotent: bool = True) -> AgentRun:
    run = AgentRun(user_id="owner", message=task_id, status="queued")
    run.metadata["runtime_context"] = {"tenant_id": "tenant-a"}
    run.metadata["task_context"] = {"task_id": task_id, "attempt": 1}
    run.steps.append(
        AgentStep(
            node_id="query",
            tool_id="products",
            action="query",
            params={"keyword": task_id},
            risk="low" if idempotent else "high",
            idempotent=idempotent,
        )
    )
    return run


def _orchestrator_factory(repository, executor):
    orchestrator = AgentOrchestrator(repository=repository, tool_executor=executor)
    orchestrator._record_tool_usage_entry = lambda *_args, **_kwargs: True
    return orchestrator


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


def test_dispatcher_runs_two_tasks_concurrently_with_stable_idempotency_keys() -> None:
    run_repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    executor = _ConcurrentExecutor()
    runs = [_queued_run("task-one"), _queued_run("task-two")]
    for run in runs:
        run_repository.save(run)
        queue.enqueue(run, requested_by="owner")
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
    assert all(queue.get(run.run_id).state == "completed" for run in runs)  # type: ignore[union-attr]


def test_expired_idempotent_step_recovers_but_non_idempotent_step_fails_closed() -> None:
    repository = InMemoryAgentRunRepository()
    executor = _ConcurrentExecutor()
    executor.release.set()

    idempotent = _queued_run("recoverable")
    idempotent.status = "running"
    idempotent.steps[0].status = "running"
    idempotent.tool_calls.append(
        ToolCall(
            step_id=idempotent.steps[0].step_id,
            node_id="query",
            tool_id="products",
            action="query",
            status="running",
        )
    )
    repository.save(idempotent)
    recovered = _orchestrator_factory(repository, executor).execute_dispatched_run(
        idempotent.run_id,
        recovered=True,
    )

    assert recovered is not None
    assert recovered.status == "completed"
    assert len(recovered.tool_calls) == 2
    assert recovered.tool_calls[0].status == "failed"
    assert recovered.tool_calls[0].error == "worker_lease_expired"
    assert recovered.tool_calls[1].metadata["idempotency_key"].endswith(recovered.steps[0].step_id)

    unsafe = _queued_run("unsafe", idempotent=False)
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


def test_dispatcher_restart_claims_expired_lease_and_completes_idempotent_task() -> None:
    repository = InMemoryAgentRunRepository()
    queue = InMemoryTaskExecutionRepository()
    executor = _ConcurrentExecutor()
    executor.release.set()
    run = _queued_run("restart-recovery")
    run.status = "running"
    run.steps[0].status = "running"
    run.tool_calls.append(
        ToolCall(
            step_id=run.steps[0].step_id,
            node_id="query",
            tool_id="products",
            action="query",
            status="running",
        )
    )
    repository.save(run)
    queue.enqueue(run, requested_by="owner")
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
    assert execution.state == "completed"
    assert recovered is not None and len(recovered.tool_calls) == 2
    assert recovered.tool_calls[0].error == "worker_lease_expired"
