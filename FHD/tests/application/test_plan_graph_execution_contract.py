"""Plan takeover validates before dispatch and preserves dependency order."""

from unittest.mock import patch

import pytest

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import Branch, PlanGraph, WorkflowNode, validate_plan_graph


def node(name, deps=()):
    return WorkflowNode(
        node_id=name,
        tool_id="business_db",
        action="read",
        params={"entity": "products", "keyword": name},
        risk="low",
        idempotent=True,
        depends_on=list(deps),
    )


def run_plan(plan):
    return AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
        user_id="test", message="read products", plan=plan
    )


def test_permuted_dag_executes_dependencies_first():
    parent, child = node("parent"), node("child", ["parent"])
    for nodes in ([child, parent], [parent, child]):
        calls = []
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=lambda *a, **kw: (
                calls.append(kw.get("params", a[2] if len(a) > 2 else {}))
                or {"success": True, "data": [{"model_number": "5003"}]}
            ),
        ):
            run = run_plan(PlanGraph(plan_id="dag", intent="test", nodes=nodes))
        assert run.status == "completed", (run.error, [s.error for s in run.steps], calls)
        assert [s.node_id for s in run.steps] == ["parent", "child"]
        assert len(calls) == 2


@pytest.mark.parametrize(
    "nodes",
    [[], [node("a", ["b"]), node("b", ["a"])], [node("a", ["missing"])], [node("a"), node("a")]],
)
def test_invalid_graph_has_zero_side_effects_across_runtimes(nodes):
    plan = PlanGraph(plan_id="invalid", intent="test", nodes=nodes)
    assert validate_plan_graph(plan)
    with patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as dispatch:
        run = run_plan(plan)
    assert run.status == "blocked" and run.error
    dispatch.assert_not_called()
    calls = []
    result = WorkflowEngine(tool_dispatcher=lambda *a: calls.append(a)).run(plan)
    assert not result.success and calls == []


def test_conditional_plan_is_explicitly_rejected_by_step_runtime():
    first = node("first")
    first.branches = [Branch(target="yes", condition={"key": "available", "equals": True})]
    first.next = "no"
    plan = PlanGraph(
        plan_id="conditional",
        intent="test",
        nodes=[first, node("yes", ["first"]), node("no", ["first"])],
    )
    with patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as dispatch:
        run = run_plan(plan)
    assert run.status == "blocked" and "conditional" in run.error
    dispatch.assert_not_called()
