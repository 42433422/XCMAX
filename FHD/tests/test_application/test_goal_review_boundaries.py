"""Goal admission stays bound to reviewed data and reports the actual failure."""

import json
from unittest.mock import Mock

from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
from app.application.workflow.planner import LLMWorkflowPlanner
from app.infrastructure.modstore_transport import MarketModelError
from app.services.tools_execution.registry import get_workflow_tool_registry


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
