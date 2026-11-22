"""elt_import 的「单文件/整批」二选一必填参数校验。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest

from app.application.workflow.clarification_node import needs_clarification
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def _registry() -> dict:
    return {
        "elt_import": {
            "actions": {
                "execute": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "required_any": [["run_id", "run_ids"]],
                }
            }
        }
    }


def _plan(params: dict) -> PlanGraph:
    node = WorkflowNode(
        node_id="elt_execute",
        tool_id="elt_import",
        action="execute",
        params=params,
        risk="high",
        idempotent=False,
    )
    return PlanGraph(plan_id="plan-1", intent="导入 Excel", nodes=[node])


def _reviewed_params(selection: dict) -> dict:
    """Bind each synthetic preview ID to its own stable reviewed version."""
    run_ids = [selection["run_id"]] if "run_id" in selection else selection["run_ids"]
    revisions = {
        run_id: sha256(f"synthetic-reviewed-preview:{run_id}".encode()).hexdigest()
        for run_id in run_ids
    }
    versions = (
        {"preview_revision": revisions[selection["run_id"]]}
        if "run_id" in selection
        else {"preview_revisions": revisions}
    )
    return {**selection, **versions}


def test_single_run_id_satisfies_requirement():
    assert needs_clarification(_plan(_reviewed_params({"run_id": "run-1"})), _registry()) == []


def test_batch_run_ids_satisfy_requirement():
    params = _reviewed_params({"run_ids": ["run-1", "run-2"]})
    assert needs_clarification(_plan(params), _registry()) == []


def test_missing_both_asks_for_either():
    items = needs_clarification(_plan({}), _registry())
    assert len(items) == 1
    assert items[0]["reason"] == "missing_required"
    assert items[0]["missing_fields"] == ["run_id", "run_ids"]
    assert "任选一种" in items[0]["question"]


@pytest.mark.parametrize(
    "answer", [{"run_id": "preview-1"}, {"run_ids": ["preview-1", "preview-2"]}]
)
def test_either_answer_updates_same_run_and_still_waits_for_approval(answer):
    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.workflow.planning_graph_policy import apply_clarification

    expected = _reviewed_params(answer)
    reviewed_versions = {key: value for key, value in expected.items() if key not in answer}
    plan = apply_clarification(_plan(deepcopy(reviewed_versions)), _registry())
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(user_id="owner", message="执行预演", plan=plan)
    assert run.status == "waiting_user"
    assert run.steps[0].params["clarification"]["missing_fields"] == ["run_id", "run_ids"]
    orchestrator.stage_clarification_answer(
        run.run_id, step_id=run.steps[0].step_id, parameters=answer, requested_by="owner"
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)
    assert continued.run_id == run.run_id
    assert continued.steps[-1].params == expected
    assert continued.status == "waiting_user"
    assert continued.tool_calls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
