"""Concurrent reads reserve the same unchanged per-run budget atomically."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from app.application.agent_orchestrator.budget import (
    budget_exceeded_payload,
    refresh_ai_budget_metadata,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call


def test_parallel_prechecked_reads_cannot_double_spend_one_unit(monkeypatch):
    dependencies = RuntimeDependencies(
        action_spec=get_tool_action_spec,
        validate=validate_tool_call,
        refresh_budget=refresh_ai_budget_metadata,
    )
    usage = RunUsageLedger(dependencies)
    monkeypatch.setattr(usage, "record_tool_usage_entry", lambda *args: True)
    executor = SimpleNamespace(execute=lambda *args, **kwargs: {"success": True, "data": []})
    runner = StepExecution(
        InMemoryAgentRunRepository(),
        executor,
        usage,
        dependencies,
        attach_artifacts=lambda *args, **kwargs: None,
        observe=lambda *args, **kwargs: {},
    )
    steps = [
        AgentStep(
            node_id=f"read-{i}", tool_id="products", action="query", risk="low", idempotent=True
        )
        for i in range(2)
    ]
    run = AgentRun(user_id="1", message="two reads", steps=steps)
    run.metadata["ai_cost_budget_units"] = 1
    gate = Barrier(2)

    def execute(step):
        # Both scheduler callbacks legitimately passed before either was billed.
        assert budget_exceeded_payload(run, additional_cost_units=1) is None
        gate.wait(timeout=3)
        runner.execute_step(run, step, runtime_context={}, node_outputs={})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, steps))
    assert sum(step.output.get("success") is True for step in steps) == 1
    assert sum(step.output.get("error_code") == "ai_cost_budget_exceeded" for step in steps) == 1
    assert len(run.tool_calls) == 1
    assert run.metadata["ai_cost_units_total"] == 1
    assert run.metadata["ai_cost_budget_units"] == 1
