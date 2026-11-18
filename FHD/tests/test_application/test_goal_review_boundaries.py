"""Goal admission stays bound to reviewed data and reports the actual failure."""

import json
from unittest.mock import Mock

import pytest

from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.infrastructure.modstore_transport import MarketModelError
from app.services.tools_execution.registry import get_workflow_tool_registry
from tests.fixtures.planner_model import goal_review_response


def _response(payload):
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def _planned():
    return _response(
        {
            "mode": "workflow",
            "intent": "query",
            "nodes": [
                {
                    "node_id": "a",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "A1"},
                }
            ],
        }
    )


def _review(*, incomplete=False):
    return _response(
        {
            "goals": [
                {"goal_id": "first", "source": "查询A1", "outcome": "execute", "node_ids": ["a"]}
            ],
            "violations": ["遗漏第二项要求 internal_review_trace"] if incomplete else [],
        }
    )


def _planner(completion):
    return LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )


def test_valid_review_rejection_is_not_reported_as_a_provider_outage():
    completion = Mock(side_effect=[_planned(), _review(incomplete=True)] * 2)
    plan = _planner(completion).plan("owner", "先查询A1，再查询B2", get_workflow_tool_registry())
    assert plan.metadata["goal_coverage_rejected"] is True
    assert plan.metadata["planning_unavailable"] is False
    callbacks, risk = Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    planner = Mock(plan=Mock(return_value=plan))
    result = PlannedWorkflowDispatch({}, callbacks, planner, risk, Mock()).handle(
        "owner", "先查询A1，再查询B2", "chat", {}, "先查询A1，再查询B2"
    )
    assert result["success"] is False
    assert result["data"]["error_code"] == "workflow_goal_coverage_rejected"
    assert result["execution"]["outcome"] == "not_executed"
    assert "先后顺序" in result["response"] and "检查模型连接" not in result["response"]
    assert "internal_review_trace" not in json.dumps(result, ensure_ascii=False)
    risk.evaluate.assert_not_called()


def test_replan_provider_failure_keeps_the_provider_failure_classification():
    completion = Mock(
        side_effect=[
            _planned(),
            _review(incomplete=True),
            MarketModelError({"status": 402}),
        ]
    )
    plan = _planner(completion).plan("owner", "先查询A1，再查询B2", get_workflow_tool_registry())
    assert plan.metadata["planning_rejected"] is True
    assert plan.metadata["planning_unavailable"] is True
    assert not plan.metadata.get("goal_coverage_rejected")
    assert "余额不足" in plan.metadata["rejection_reason"]
    assert completion.call_count == 3


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


@pytest.mark.parametrize("native", [False, True])
def test_retired_import_is_rejected_before_goal_review_and_dispatch(native):
    message = "将 owned.xlsx 导入客户库"
    graph = plan_to_dict(_legacy_import_graph())
    payload = {"mode": "workflow", "risk_level": "high", "nodes": graph["nodes"]}
    requests = []

    def complete(**kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        requests.append(request)
        if request["task"] == "audit_goal_coverage":
            return goal_review_response(
                request, source=message, node_ids=["import"], outcome="execute"
            )
        if native and len(requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "SubmitWorkflowPlan",
                                        "arguments": json.dumps(payload),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        # A shape repair must not reintroduce the retired operation either.
        return _response(payload)

    callbacks, risk = Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    result = PlannedWorkflowDispatch({}, callbacks, _planner(complete), risk, Mock()).handle(
        "owner", message, "chat", {}, message
    )
    assert result["success"] is False
    assert result["execution"]["outcome"] == "not_executed"
    assert not any(request["task"] == "audit_goal_coverage" for request in requests)
    assert any("import_excel_to_database" in str(request.get("error")) for request in requests)
    risk.evaluate.assert_not_called()
    callbacks._capture_agent_run_interaction.assert_not_called()


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
                {"run_id": "{{preview.data.run_id}}"},
                depends_on=["preview"],
            ),
        ],
    )
    assert validate_required_params(plan, get_workflow_tool_registry()) is None
    assert plan.nodes[1].depends_on == ["preview"]
