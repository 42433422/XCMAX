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


@pytest.mark.parametrize("available,chosen", [(True, "yes"), (False, "no")])
@pytest.mark.parametrize("reverse", [False, True])
def test_conditional_plan_executes_only_selected_branch(available, chosen, reverse):
    first = node("first")
    first.branches = [Branch(target="yes", condition={"key": "available", "equals": True})]
    first.next = "no"
    nodes = [first, node("yes"), node("no"), node("after_no", ["no"])]
    plan = PlanGraph(plan_id="conditional", intent="test", nodes=nodes[::-1] if reverse else nodes)
    calls = []

    def dispatch(tool, action, params):
        calls.append(params["keyword"])
        return {"success": True, "available": available, "data": [{"model_number": "5003"}]}

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=dispatch,
    ):
        run = run_plan(plan)
    assert run.status == "completed", run.error
    assert calls == (["first", "yes"] if chosen == "yes" else ["first", "no", "after_no"])
    assert (
        next(s for s in run.steps if s.node_id == ("no" if chosen == "yes" else "yes")).status
        == "skipped"
    )


def test_unmatched_branch_without_default_has_no_side_effects():
    first = node("first")
    first.branches = [Branch(target="yes", condition={"key": "available", "equals": True})]
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "data": [{"model_number": "5003"}], "available": False},
    ) as dispatch:
        run = run_plan(PlanGraph(plan_id="no-match", intent="test", nodes=[node("yes"), first]))
    assert run.status == "completed"
    assert dispatch.call_count == 1


def test_branch_decision_survives_approval_and_repository_round_trip():
    import json

    from app.application.agent_orchestrator.run_models import agent_run_from_dict

    first = node("first")
    first.next = "no"
    first.branches = [Branch(target="yes", condition={"key": "available", "equals": True})]
    repo = InMemoryAgentRunRepository()
    runner = AgentOrchestrator(repository=repo)
    run = runner.start_run_from_plan(
        user_id="owner",
        message="test",
        auto_execute=False,
        plan=PlanGraph(plan_id="approval", intent="test", nodes=[node("no"), node("yes"), first]),
    )
    next(s for s in run.steps if s.node_id == "yes").risk = "high"
    calls = []

    def dispatch(tool, action, params):
        calls.append(params["keyword"])
        return {"success": True, "data": [{"model_number": "5003"}], "available": True}

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=dispatch,
    ):
        runner._execute_ready_steps(run, runtime_context={})
        assert run.status == "waiting_user"
        repo.save(agent_run_from_dict(json.loads(json.dumps(run.to_dict()))))
        restored = AgentOrchestrator(repository=repo).continue_run(
            run.run_id, approved_step_id="yes", approved_by="owner"
        )
    assert restored.status == "completed"
    assert calls == ["first", "yes"]


def test_failed_router_never_dispatches_any_branch():
    first = node("first")
    first.next = "next"
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": False, "message": "failed"},
    ) as dispatch:
        run = run_plan(
            PlanGraph(plan_id="failed-router", intent="test", nodes=[node("next"), first])
        )
    assert run.status == "failed"
    assert dispatch.call_count == 1
