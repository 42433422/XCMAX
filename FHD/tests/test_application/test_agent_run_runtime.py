from __future__ import annotations

import threading
import time
from unittest.mock import patch

from app.application.agent_orchestrator import (
    AgentOrchestrator,
    AgentRun,
    AgentRunRuntime,
    AgentStep,
    InMemoryAgentRunRepository,
    ToolCall,
)
from app.application.workflow.types import PlanGraph, WorkflowNode


def _two_step_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="plan-background",
        intent="background_read",
        nodes=[
            WorkflowNode(
                node_id="read_first",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "first"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="read_second",
                tool_id="business_db",
                action="read",
                params={"entity": "products", "keyword": "second"},
                risk="low",
                idempotent=True,
                depends_on=["read_first"],
            ),
        ],
    )


def _wait_for_status(repo: InMemoryAgentRunRepository, run_id: str, status: str) -> AgentRun:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = repo.get(run_id)
        if run is not None and run.status == status:
            return run
        time.sleep(0.01)
    run = repo.get(run_id)
    raise AssertionError(f"expected {status}, got {run.status if run else 'missing'}")


def test_background_run_pauses_at_checkpoint_and_resumes() -> None:
    repo = InMemoryAgentRunRepository()
    runtime = AgentRunRuntime(repository=repo, max_workers=1)
    first_started = threading.Event()
    release_first = threading.Event()
    call_count = 0

    def execute_tool(_tool_id, _action, params):
        nonlocal call_count
        call_count += 1
        if params.get("keyword") == "first":
            first_started.set()
            assert release_first.wait(2)
        return {"success": True, "data": [{"keyword": params.get("keyword")}]}

    run = AgentOrchestrator(repository=repo).start_run_from_plan(
        user_id="u1",
        message="后台执行两个查询",
        plan=_two_step_plan(),
        auto_execute=False,
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=execute_tool,
    ):
        runtime.submit(run.run_id)
        assert first_started.wait(2)
        paused_request = runtime.request_pause(run.run_id, requested_by="tester")
        assert paused_request is not None
        assert paused_request.metadata["runtime"]["pause_requested"] is True
        release_first.set()
        paused = _wait_for_status(repo, run.run_id, "paused")

        assert paused.steps[0].status == "completed"
        assert paused.steps[1].status == "pending"
        assert paused.metadata["checkpoint"]["completed_step_ids"] == [paused.steps[0].step_id]
        assert "run.paused" in [event.event_type for event in paused.events]

        runtime.resume(run.run_id, requested_by="tester")
        completed = _wait_for_status(repo, run.run_id, "completed")

    runtime.stop(wait=True)
    assert call_count == 2
    assert all(step.status == "completed" for step in completed.steps)
    assert "run.resumed" in [event.event_type for event in completed.events]


def test_background_cancel_stops_before_next_step() -> None:
    repo = InMemoryAgentRunRepository()
    runtime = AgentRunRuntime(repository=repo, max_workers=1)
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []

    def execute_tool(_tool_id, _action, params):
        calls.append(str(params.get("keyword")))
        if params.get("keyword") == "first":
            first_started.set()
            assert release_first.wait(2)
        return {"success": True, "data": []}

    run = AgentOrchestrator(repository=repo).start_run_from_plan(
        user_id="u1",
        message="取消后台任务",
        plan=_two_step_plan(),
        auto_execute=False,
    )
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=execute_tool,
    ):
        runtime.submit(run.run_id)
        assert first_started.wait(2)
        runtime.cancel(run.run_id, requested_by="tester")
        release_first.set()
        cancelled = _wait_for_status(repo, run.run_id, "cancelled")

    runtime.stop(wait=True)
    assert calls == ["first"]
    assert cancelled.steps[0].status == "completed"
    assert cancelled.steps[1].status == "pending"
    assert "run.cancelled" in [event.event_type for event in cancelled.events]


def test_runtime_recovers_idempotent_step_but_guards_non_idempotent_step() -> None:
    repo = InMemoryAgentRunRepository()
    idempotent = AgentRun(user_id="u1", message="恢复查询", status="running")
    idempotent.plan_id = "plan-recover-read"
    idempotent.steps.append(
        AgentStep(
            node_id="read",
            tool_id="business_db",
            action="read",
            params={"entity": "products"},
            risk="low",
            idempotent=True,
            status="running",
        )
    )
    idempotent.tool_calls.append(
        ToolCall(
            step_id=idempotent.steps[0].step_id,
            node_id="read",
            tool_id="business_db",
            action="read",
            status="running",
        )
    )
    repo.save(idempotent)

    unsafe = AgentRun(user_id="u1", message="恢复写入", status="running")
    unsafe.plan_id = "plan-recover-write"
    unsafe.steps.append(
        AgentStep(
            node_id="write",
            tool_id="business_db",
            action="write",
            params={"entity": "customers", "operation": "create", "payload": {"name": "A"}},
            risk="medium",
            idempotent=False,
            status="running",
        )
    )
    unsafe.tool_calls.append(
        ToolCall(
            step_id=unsafe.steps[0].step_id,
            node_id="write",
            tool_id="business_db",
            action="write",
            status="running",
        )
    )
    repo.save(unsafe)

    runtime = AgentRunRuntime(repository=repo, max_workers=1)
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "data": []},
    ):
        recovery = runtime.start(recover=True)
        completed = _wait_for_status(repo, idempotent.run_id, "completed")

    guarded = repo.get(unsafe.run_id)
    runtime.stop(wait=True)
    assert recovery == {"recovered": 1, "waiting_user": 1, "cancelled": 0}
    assert completed.tool_calls[0].metadata["interrupted_by_restart"] is True
    assert guarded is not None
    assert guarded.status == "waiting_user"
    assert guarded.steps[0].status == "waiting_user"
    assert "step.recovery_confirmation_required" in [event.event_type for event in guarded.events]
