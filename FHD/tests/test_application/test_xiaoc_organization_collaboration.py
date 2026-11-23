"""Regression contracts for the existing employee collaboration runtime."""

from __future__ import annotations

import json

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.employee_runtime.orchestrator import (
    EmployeeOrchestrator,
    _project_collaboration_result,
)
from app.application.employee_runtime.task_continuity import (
    TaskContinuityRuntime,
    ledger_path,
)
from app.domain.employee.collaboration_graph import CollaborationGraph
from tests.test_application.test_task_continuity_acceptance import _effects, _install, _run


def _graph():
    return CollaborationGraph(
        {"lead": ["sales", "finance"], "sales": ["warehouse"], "warehouse": [], "finance": []}
    )


@pytest.mark.parametrize("edges", [{"lead": ["lead"]}, {"lead": ["sales"], "sales": ["lead"]}])
def test_reachable_cycle_fails_before_agent_run(edges):
    result = EmployeeOrchestrator(CollaborationGraph(edges)).run_upstream("lead", "review")
    assert result["success"] is False
    assert result["error_code"] == "employee_dependency_cycle"
    assert not result["node_outputs"]


def test_unrelated_cycle_does_not_block_valid_collaboration():
    graph = _graph()
    graph.add("unrelated", ["unrelated"])
    plan = EmployeeOrchestrator(graph).build_plan("lead", "review", include_root=False)
    assert plan is not None
    assert [node.node_id for node in plan.nodes] == ["warehouse", "sales", "finance"]
    assert plan.nodes[1].depends_on == ["warehouse"]


def _completed_run(plan):
    steps = [
        AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=node.action,
            depends_on=node.depends_on,
            status="completed",
            output={"success": True, "employee_id": node.node_id},
        )
        for node in plan.nodes
    ]
    return AgentRun(
        user_id="1",
        message="review",
        plan_id=plan.plan_id,
        status="completed",
        steps=steps,
        final_output={"node_outputs": {step.node_id: dict(step.output) for step in steps}},
    )


@pytest.mark.parametrize("fault", ["failed", "missing", "duplicate", "pending", "changed", "extra"])
def test_completed_group_status_does_not_override_original_node_receipts(fault):
    plan = EmployeeOrchestrator(_graph()).build_plan("lead", "review", include_root=False)
    assert plan is not None
    run = _completed_run(plan)
    assert _project_collaboration_result("lead", plan, run)["success"] is True
    outputs = run.final_output["node_outputs"]
    if fault == "failed":
        run.steps[1].status = "failed"
    elif fault == "missing":
        run.steps.pop()
    elif fault == "duplicate":
        run.steps[1] = run.steps[0]
    elif fault == "pending":
        run.steps[0].output["execution_state"] = "queued"
        outputs[run.steps[0].node_id] = dict(run.steps[0].output)
    elif fault == "changed":
        outputs[run.steps[0].node_id] = {"success": True, "employee_id": "different"}
    else:
        outputs["foreign"] = {"success": True}
    result = _project_collaboration_result("lead", plan, run)
    assert result["success"] is False
    assert not result["node_outputs"]
    assert result["independent_verified"] is False


def test_tenant_mismatch_blocks_before_execution():
    from app.infrastructure.tenant_scope import tenant_scope

    with tenant_scope(1):
        result = EmployeeOrchestrator(_graph()).run_upstream(
            "lead", "review", runtime_context={"user_id": 1, "tenant_id": 2}
        )
    assert result["error_code"] == "employee_tenant_scope_invalid"
    assert not result["node_outputs"]


def _specs():
    return [
        {"employee_id": name, "tool": "child_work", "params": {"token": name}}
        for name in ("sales", "warehouse", "finance")
    ]


def test_split_is_atomic_idempotent_and_responsibility_bound(tmp_path):
    _install(tmp_path, "child_work")
    scope = {"tenant_id": "t1", "user_id": "u1"}
    parent = _run(tmp_path, "lead", continuity_action="start", **scope)["task_id"]

    def split(specs):
        return _run(
            tmp_path, "lead", continuity_action="split", task_id=parent, children=specs, **scope
        )

    invalid = _specs()
    invalid[1] = {"employee_id": ""}
    assert split(invalid)["error_code"] == "invalid_child_spec"
    first = split(_specs())
    children = first["task"]["child_task_ids"]
    assert len(children) == 3
    assert split(_specs())["task"]["child_task_ids"] == children
    changed = _specs()
    changed[-1]["params"]["token"] = "different"
    assert split(changed)["error_code"] == "split_plan_conflict"
    wrong = _run(tmp_path, "lead", continuity_action="child_return", task_id=children[0], **scope)
    assert wrong["success"] is False
    assert not _effects(tmp_path, "child_work")
    for spec, child in zip(_specs(), children):
        assert _run(
            tmp_path, spec["employee_id"], continuity_action="child_return", task_id=child, **scope
        )["business_success"]
    read = _run(tmp_path, "lead", continuity_action="read", task_id=parent, **scope)
    assert read["business_success"]
    assert len(_effects(tmp_path, "child_work")) == 3


def test_sealed_split_rechecks_employee_identity_before_new_work(tmp_path):
    _install(tmp_path, "child_work")
    folder = tmp_path / "employees"
    folder.mkdir(exist_ok=True)
    for name in ("sales", "warehouse", "finance"):
        (folder / f"{name}.json").write_text(
            json.dumps({"employee_id": name, "tenant_id": "t1"}), encoding="utf-8"
        )
    # The sealed binding is supplied by the host, not the child request.
    runtime = TaskContinuityRuntime(
        ledger_path(tmp_path),
        workspace=tmp_path,
        runtime_context={"_actor_authorization": {}, "user_id": "u1", "tenant_id": "t1"},
    )
    scope = {"tenant_id": "t1", "user_id": "u1"}
    parent = runtime.dispatch("lead", "review", {"op": "start", **scope})["task_id"]
    foreign = folder / "finance.json"
    foreign.write_text(
        json.dumps({"employee_id": "finance", "tenant_id": "another"}), encoding="utf-8"
    )
    request = {"op": "split", "task_id": parent, "children": _specs(), **scope}
    assert runtime.dispatch("lead", "", request)["error_code"] == "handoff_cross_tenant"
    foreign.write_text(json.dumps({"employee_id": "finance", "tenant_id": "t1"}), encoding="utf-8")
    children = runtime.dispatch("lead", "", request)["task"]["child_task_ids"]
    (folder / "sales.json").unlink()
    denied = runtime.dispatch("sales", "", {"op": "child_return", "task_id": children[0], **scope})
    assert denied["success"] is False
    assert not _effects(tmp_path, "child_work")
