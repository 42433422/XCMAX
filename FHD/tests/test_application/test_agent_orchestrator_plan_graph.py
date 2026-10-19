from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_agent_usage_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)


def _node(node_id: str, **kwargs):
    from app.application.workflow.types import WorkflowNode

    return WorkflowNode(
        node_id=node_id,
        tool_id="business_db",
        action="read",
        params={"entity": "products"},
        risk="low",
        idempotent=True,
        **kwargs,
    )


def _run(plan, side_effect=None):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=side_effect,
    ) as execute:
        run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
            user_id="u1",
            message="plan graph test",
            plan=plan,
            runtime_context={"source": "plan-graph-test"},
        )
    return run, execute


def test_conditional_branches_are_mutually_exclusive():
    from app.application.workflow.types import Branch, PlanGraph

    plan = PlanGraph(
        plan_id="p-branch",
        intent="branch",
        nodes=[
            _node(
                "probe",
                branches=[
                    Branch(target="low_path", condition={"key": "low_stock", "equals": True}),
                    Branch(target="ok_path", condition={"key": "low_stock", "equals": False}),
                ],
            ),
            _node("low_path"),
            _node("ok_path"),
        ],
    )
    run, execute = _run(
        plan,
        side_effect=lambda *a, **k: {
            "success": True,
            "data": [{"model_number": "X5003"}],
            "low_stock": True,
        },
    )

    statuses = {step.node_id: step.status for step in run.steps}
    assert statuses == {"probe": "completed", "low_path": "completed", "ok_path": "skipped"}
    assert run.status == "completed"
    executed = [step.node_id for step in run.steps if step.status == "completed"]
    assert executed == ["probe", "low_path"]
    assert execute.call_count == 2


def test_out_of_order_dag_executes_in_dependency_order():
    from app.application.workflow.types import PlanGraph

    plan = PlanGraph(
        plan_id="p-order",
        intent="order",
        nodes=[_node("second", depends_on=["first"]), _node("first")],
    )
    run, execute = _run(
        plan,
        side_effect=lambda *a, **k: {"success": True, "data": [{"model_number": "X5003"}]},
    )

    assert run.status == "completed"
    assert [step.status for step in run.steps] == ["completed", "completed"]
    assert execute.call_count == 2


def test_dependency_cycle_is_rejected_without_side_effects():
    from app.application.workflow.types import PlanGraph

    plan = PlanGraph(
        plan_id="p-cycle",
        intent="cycle",
        nodes=[
            _node("a", depends_on=["b"]),
            _node("b", depends_on=["a"]),
        ],
    )
    run, execute = _run(plan, side_effect=AssertionError("must not execute"))

    assert run.status == "failed"
    assert "cycle" in run.error
    assert run.steps == []
    assert run.tool_calls == []
    execute.assert_not_called()


def test_empty_plan_is_not_completed():
    from app.application.workflow.types import PlanGraph

    run, execute = _run(PlanGraph(plan_id="p-empty", intent="empty"), side_effect=None)

    assert run.status == "blocked"
    assert run.status != "completed"
    assert run.error
    execute.assert_not_called()
