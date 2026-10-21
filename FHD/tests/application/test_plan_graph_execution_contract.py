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


def test_permuted_dag_executes_dependencies_first(local_tools):
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
def test_conditional_plan_executes_only_selected_branch(available, chosen, reverse, local_tools):
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


def test_unmatched_branch_without_default_has_no_side_effects(local_tools):
    first = node("first")
    first.branches = [Branch(target="yes", condition={"key": "available", "equals": True})]
    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={"success": True, "data": [{"model_number": "5003"}], "available": False},
    ) as dispatch:
        run = run_plan(PlanGraph(plan_id="no-match", intent="test", nodes=[node("yes"), first]))
    assert run.status == "completed"
    assert dispatch.call_count == 1


def test_branch_decision_survives_approval_and_repository_round_trip(
    local_tools,
):
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


def test_failed_router_never_dispatches_any_branch(local_tools):
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


@pytest.mark.parametrize(
    "shape", ["nested", "prerequisite", "descendant", "diamond", "hard_join", "shared"]
)
@pytest.mark.parametrize("runtime", ["agent", "workflow"])
def test_control_and_data_dependency_parity(shape, runtime, local_tools):
    root, yes, no, end = [node(name) for name in ("root", "yes", "no", "end")]
    root.next = "yes"
    root.branches = [Branch("no", {"key": "available", "equals": False})]
    nodes, expected = [root, no, yes], {"root", "yes"}
    if shape == "nested":
        no.next = "end"
    elif shape == "prerequisite":
        root.depends_on = ["end"]
        expected.add("end")
    elif shape in {"descendant", "hard_join"}:
        end.depends_on = ["no"] if shape == "descendant" else ["yes", "no"]
    elif shape == "diamond":
        yes.next = no.next = "end"
        expected.add("end")
    else:
        root.branches = [Branch("end", {"key": "available", "equals": False})]
        no.next = "end"
        expected.update({"no", "end"})
    plan = PlanGraph(plan_id=shape, intent="test", nodes=[end, *nodes])
    calls = []

    def dispatch(tool_id, action, params):
        calls.append(params["keyword"])
        return {"success": True, "available": True, "data": [{"model_number": "5003"}]}

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        side_effect=dispatch,
    ):
        result = (
            run_plan(plan)
            if runtime == "agent"
            else WorkflowEngine(dispatch).run(plan, parallel=False)
        )
    assert (result.status == "completed") if runtime == "agent" else result.success
    assert set(calls) == expected and len(calls) == len(expected)
    if shape == "prerequisite":
        assert calls.index("end") < calls.index("root") < calls.index("yes")


def test_conditional_checkpoint_resumes_without_replaying_completed_calls():
    from app.application.workflow.checkpointer import WorkflowCheckpointer

    root, yes, no = [node(name) for name in ("root", "yes", "no")]
    root.next = "yes"
    root.branches = [Branch("no", {"key": "available", "equals": False})]
    calls, cp = [], WorkflowCheckpointer()

    def dispatch(tool_id, action, params):
        calls.append(params["keyword"])
        return {"success": True, "available": True}

    engine = WorkflowEngine(dispatch)
    plan = PlanGraph(plan_id="resume", intent="test", nodes=[root, yes, no])
    assert engine.run(plan, checkpointer=cp, parallel=False).success
    checkpoint = cp.list_checkpoints(plan.plan_id)[-1]
    assert engine.resume_run(
        plan, checkpoint["checkpoint_id"], checkpointer=cp, parallel=False
    ).success
    assert calls == ["root", "yes"]


def test_router_progress_is_checkpointed_before_downstream_failure():
    from app.application.workflow.checkpointer import WorkflowCheckpointer

    root, write, fail = [node(name) for name in ("root", "write", "fail")]
    root.next, write.next = "write", "fail"
    cp = WorkflowCheckpointer()
    engine = WorkflowEngine(
        lambda tool_id, action, params: {"success": params["keyword"] != "fail"}
    )
    plan = PlanGraph(plan_id="failure", intent="test", nodes=[root, write, fail])
    assert not engine.run(plan, checkpointer=cp, max_retries=0, parallel=False).success
    assert cp.list_checkpoints(plan.plan_id)[-1]["executed_nodes"] == ["root", "write"]


@pytest.mark.parametrize("failure", ["read", "write1", "write2"])
def test_batch_failure_stops_writes_and_preserves_successful_progress(failure):
    from app.application.workflow.checkpointer import WorkflowCheckpointer

    names = ["read", "write1", "write2"]
    nodes = [node(name) for name in names]
    for item in nodes[1:]:
        item.risk, item.idempotent = "high", False
    calls, cp = [], WorkflowCheckpointer()

    def dispatch(tool_id, action, params):
        calls.append(params["keyword"])
        return {"success": params["keyword"] != failure}

    plan = PlanGraph(plan_id="batch-failure", intent="test", nodes=nodes)
    result = WorkflowEngine(dispatch).run(plan, checkpointer=cp, max_retries=0, parallel=False)
    assert not result.success
    assert calls == names[: names.index(failure) + 1]
    checkpoints = cp.list_checkpoints(plan.plan_id)
    if failure == "read":
        assert checkpoints == []
    else:
        assert set(checkpoints[-1]["executed_nodes"]) == set(names[: names.index(failure)])


@pytest.mark.parametrize("outputs", [{}, {"root": None}, None])
def test_resume_missing_router_evidence_fails_closed(outputs):
    from app.application.workflow.checkpointer import WorkflowCheckpointer

    root, yes = node("root"), node("yes")
    root.next = "yes"
    plan = PlanGraph(plan_id="missing-evidence", intent="test", nodes=[root, yes])
    cp, calls = WorkflowCheckpointer(), []
    checkpoint = cp.save_checkpoint(plan.plan_id, 1, {"node_outputs": outputs}, ["root"])
    result = WorkflowEngine(lambda *args: calls.append(args)).resume_run(
        plan, checkpoint, checkpointer=cp, parallel=False
    )
    assert not result.success and calls == []


@pytest.mark.parametrize("parallel", [False, True])
def test_partial_read_resume_preserves_each_attempt_output(parallel):
    from app.application.workflow.checkpointer import WorkflowCheckpointer

    plan = PlanGraph(plan_id="partial-read", intent="test", nodes=[node("bad"), node("good")])
    cp = WorkflowCheckpointer()
    engine = WorkflowEngine(lambda tool_id, action, params: {"success": params["keyword"] != "bad"})
    assert not engine.run(plan, checkpointer=cp, parallel=parallel, max_retries=0).success
    checkpoint = cp.latest_checkpoint(plan.plan_id)
    assert checkpoint["executed_nodes"] == ["good"]
    calls = []

    def dispatch(tool_id, action, params):
        calls.append(params["keyword"])
        return {"success": True}

    engine = WorkflowEngine(dispatch)
    assert engine.resume_run(
        plan, checkpoint["checkpoint_id"], checkpointer=cp, parallel=parallel
    ).success
    assert calls == ["bad"]
    replay = engine.replay_run(plan.plan_id, checkpointer=cp)
    attempts = [result for result in replay.node_results if result.node_id == "bad"]
    assert [(result.success, result.output["success"]) for result in attempts] == [
        (False, False),
        (True, True),
    ]
