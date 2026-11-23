"""Persisted business graphs keep retired-tool and ELT admission guards."""

from unittest.mock import Mock

from app.application.agent_orchestrator.param_references import resolve_references
from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.services.tools_execution.registry import get_workflow_tool_registry


def _legacy_import_graph():
    return PlanGraph(
        plan_id="legacy-import",
        intent="import",
        risk_level="high",
        nodes=[
            WorkflowNode(
                "import",
                "import_excel_to_database",
                "import",
                {"file_path": "owned.xlsx", "import_type": "customers", "confirm": True},
                risk="high",
            )
        ],
    )


def test_persisted_retired_import_cannot_resume_even_with_complete_confirmed_params():
    from app.application.agent_orchestrator import (
        AgentOrchestrator,
        AgentRun,
        AgentStep,
        InMemoryAgentRunRepository,
    )

    plan = _legacy_import_graph()
    error = validate_required_params(plan, get_workflow_tool_registry())
    assert "import_excel_to_database" in error and "ELT" in error
    node = plan.nodes[0]
    repository, executor = InMemoryAgentRunRepository(), Mock()
    pending = AgentRun(
        user_id="owner",
        message="将 owned.xlsx 导入客户库",
        plan_id=plan.plan_id,
        status="waiting_user",
        steps=[
            AgentStep(
                node.node_id,
                node.tool_id,
                node.action,
                dict(node.params),
                risk="high",
                status="waiting_user",
            )
        ],
        metadata={"plan": plan_to_dict(plan)},
    )
    repository.save(pending)
    resumed = AgentOrchestrator(repository=repository, tool_executor=executor).continue_run(
        pending.run_id, approved_by="owner", approved_step_id=node.node_id
    )
    assert resumed.status == "blocked"
    assert "approval.resume_plan_rejected" in [event.event_type for event in resumed.events]
    assert resumed.steps[0].params == node.params
    assert resumed.tool_calls == []
    executor.execute.assert_not_called()
    executor.execute_with_deadline.assert_not_called()


def test_elt_preview_and_dependent_execution_remain_valid():
    plan = PlanGraph(
        plan_id="elt-import",
        intent="import",
        nodes=[
            WorkflowNode("preview", "elt_import", "preview", {"file_path": "owned.xlsx"}),
            WorkflowNode(
                "execute",
                "elt_import",
                "execute",
                {
                    "run_id": "{{preview.data.run_id}}",
                    "preview_revision": "{{preview.data.preview_revision}}",
                },
                depends_on=["preview"],
            ),
        ],
    )
    assert validate_required_params(plan, get_workflow_tool_registry()) is None
    assert plan.nodes[1].depends_on == ["preview"]
    original_preview = {"run_id": "owned-preview", "preview_revision": "a" * 64}
    problems = []
    assert (
        resolve_references(plan.nodes[1].params, {"preview": {"data": original_preview}}, problems)
        == original_preview
    )
    assert problems == []
