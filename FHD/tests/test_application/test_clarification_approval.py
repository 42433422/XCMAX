from types import SimpleNamespace
from unittest.mock import Mock

from app.application.ai_chat_app_service_aichatapplicationservice_mixin03 import (
    _AIChatApplicationServicePart03Mixin,
)
from app.application.workflow.types import PlanGraph, WorkflowNode


def test_selecting_candidate_does_not_approve_deletion():
    node = WorkflowNode(
        node_id="delete", tool_id="customers", action="delete", params={}, risk="high"
    )
    plan = PlanGraph(plan_id="p", intent="delete_customer", nodes=[node])
    pending = {
        "plan": plan,
        "target_node_id": "delete",
        "clarify_node_id": "clarify",
        "runtime_context": {},
        "clarification": {"candidates": [{"id": 42, "name": "星光"}]},
    }
    service = SimpleNamespace(
        _pending_workflows={"u": pending},
        approval_service=Mock(),
        _persist_plan_state=Mock(),
        _run_workflow_with_state_updates=Mock(side_effect=AssertionError("must await approval")),
    )
    service.approval_service.get_approval_required_nodes.return_value = [node]
    response = _AIChatApplicationServicePart03Mixin._continue_after_clarification(
        service, "u", pending, "42"
    )
    assert response["data"]["action"] == "workflow_confirmation_required"
    assert service._pending_workflows["u"]["approval_required"] is True
    assert service._pending_workflows["u"]["approval_nodes"][0]["params"]["id"] == "42"
    assert service._pending_workflows["u"]["runtime_context"]["_clarify_answers"]["clarify"][
        "confirmed"
    ]
    service._run_workflow_with_state_updates.assert_not_called()


def test_no_approval_requirement_leaves_existing_continuation_available():
    from app.application.workflow.clarification_approval import require_approval_after_clarification

    service = SimpleNamespace(
        approval_service=Mock(), _pending_workflows={}, _persist_plan_state=Mock()
    )
    service.approval_service.get_approval_required_nodes.return_value = []
    assert (
        require_approval_after_clarification(
            service, "u", PlanGraph(plan_id="p", intent="query"), {}, ""
        )
        is None
    )
    assert service._pending_workflows == {}
    service._persist_plan_state.assert_not_called()
