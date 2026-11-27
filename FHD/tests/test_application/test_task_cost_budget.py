"""Task cost constraints remain binding across graph interaction and resume."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.application.agent_orchestrator.budget import (
    apply_ai_budget_metadata,
    budget_exceeded_payload,
    extract_ai_cost_budget_units,
    refresh_ai_budget_metadata,
)
from tests.test_application.test_agent_orchestrator import (
    _isolated_agent_usage_ledger as _isolated_agent_usage_ledger,
)


@pytest.mark.parametrize("value", [0, 3, "3", " 3 ", 3.0])
def test_integral_cost_budgets_remain_compatible(value):
    assert extract_ai_cost_budget_units({"ai_cost_budget_units": value}) == int(value)


@pytest.mark.parametrize(
    "value", [True, False, -1, 1.5, "bad", "1.5", [], {}, float("inf"), float("nan")]
)
def test_explicit_invalid_cost_budget_refuses_admission_without_raising(value):
    run = SimpleNamespace(metadata={})
    apply_ai_budget_metadata(run, {"ai_cost_budget_units": value, "budget_units": 100})
    assert run.metadata["ai_cost_budget_units"] == 0
    assert run.metadata["ai_cost_budget_invalid_fields"] == ["ai_cost_budget_units"]
    refusal = budget_exceeded_payload(run, additional_cost_units=0)
    assert refusal and refusal["error_code"] == "ai_cost_budget_invalid"


def test_persisted_invalid_budget_also_refuses_before_refresh():
    run = SimpleNamespace(metadata={"ai_cost_budget_units": "invalid"})
    assert (
        budget_exceeded_payload(run, additional_cost_units=1)["error_code"]
        == "ai_cost_budget_invalid"
    )
    refresh_ai_budget_metadata(run)
    assert run.metadata["ai_cost_budget_units"] == 0
    assert run.metadata["ai_cost_budget_invalid_fields"] == ["ai_cost_budget_units"]


def test_all_cost_constraints_tighten_the_persisted_budget_without_resetting_usage():
    assert extract_ai_cost_budget_units({}, {"ai_cost_budget_units": None}) is None
    assert (
        extract_ai_cost_budget_units(
            {"ai_cost_budget_units": 4, "budget_units": 100}, {"max_ai_cost_units": 7}
        )
        == 4
    )
    run = SimpleNamespace(metadata={"ai_cost_budget_units": 4, "ai_cost_units_total": 3})
    for source in ({"budget_units": 100}, {"ai_cost_budget_units": None}, {}):
        apply_ai_budget_metadata(run, source)
        assert run.metadata["ai_cost_budget_units"] == 4
        assert run.metadata["ai_cost_budget_remaining_units"] == 1
        assert run.metadata["ai_cost_units_total"] == 3
    apply_ai_budget_metadata(run, {"cost_budget_units": 2})
    assert run.metadata["ai_cost_budget_units"] == 2
    assert run.metadata["ai_cost_budget_exceeded"] is True


@pytest.mark.parametrize("interaction", ["approval", "confirmation", "clarification"])
def test_graph_resume_cannot_enlarge_the_original_cost_budget(interaction):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.clarification_node import build_clarify_node
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    target = WorkflowNode(
        "business", "business_db", "read", {"entity": "products"}, risk="low", idempotent=True
    )
    nodes = [target]
    if interaction == "approval":
        target.action = "write"
        target.params = {
            "entity": "customers",
            "operation": "create",
            "payload": {"unit_name": "budget fixture"},
        }
    else:
        ambient = {"node_id": "question"}
        if interaction == "clarification":
            target.params = {}
            ambient.update(
                target_node_id="business",
                clarification={"reason": "missing_required", "missing_fields": ["entity"]},
            )
        nodes.insert(
            0,
            (
                build_clarify_node("请补充查询范围", ambient=ambient)
                if interaction == "clarification"
                else WorkflowNode(
                    "question", "clarify", "ask", {"question": "请确认查询范围"}, idempotent=True
                )
            ),
        )
        target.depends_on = ["question"]
    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    with (
        patch(
            "app.application.agent_orchestrator.tool_permission.actor_tool_denial",
            return_value=None,
        ),
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": []},
        ) as dispatch,
    ):
        run = orchestrator.start_run_from_plan(
            user_id="owner",
            message="预算内执行业务",
            plan=PlanGraph(
                plan_id=f"budget-{interaction}",
                intent="budget-check",
                nodes=nodes,
                metadata={"ai_cost_budget_units": 0},
            ),
        )
        assert run.status == "waiting_user", run.error
        context = {"ai_cost_budget_units": 99, "budget_units": 1000}
        if interaction == "approval":
            resumed = orchestrator.continue_run(
                run.run_id, approved_by="owner", runtime_context=context
            )
        else:
            kwargs = {
                "answered_by": "owner",
                "clarification_step_id": run.steps[0].step_id,
                "confirmed": True,
                "runtime_context": context,
            }
            resumed = (
                orchestrator.continue_plan_confirmation(run.run_id, **kwargs)
                if interaction == "confirmation"
                else orchestrator.continue_after_clarification(
                    run.run_id, parameters={"entity": "products"}, **kwargs
                )
            )
    assert resumed.status == "failed", resumed.error
    assert resumed.metadata["ai_cost_budget_units"] == 0
    assert resumed.tool_calls == []
    assert resumed.error == "AI cost budget exceeded"
    assert repo.get(run.run_id).metadata["ai_cost_budget_units"] == 0
    dispatch.assert_not_called()
