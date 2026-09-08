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


def test_missing_product_identity_is_filled_then_approval_is_required():
    node = WorkflowNode(
        node_id="create", tool_id="products", action="create", params={"price": 25.5}, risk="medium"
    )
    plan = PlanGraph(plan_id="p", intent="create_product", nodes=[node])
    pending = {
        "plan": plan,
        "target_node_id": "create",
        "clarify_node_id": "clarify",
        "runtime_context": {},
        "clarification": {
            "reason": "missing_required",
            "field": "name_or_model",
            "missing_fields": ["name_or_model"],
        },
    }
    service = SimpleNamespace(
        _pending_workflows={"u": pending},
        approval_service=Mock(),
        _persist_plan_state=Mock(),
        _run_workflow_with_state_updates=Mock(side_effect=AssertionError("must await approval")),
    )
    service.approval_service.get_approval_required_nodes.return_value = [node]
    response = _AIChatApplicationServicePart03Mixin._continue_after_clarification(
        service, "u", pending, "A100"
    )
    assert response["data"]["action"] == "workflow_confirmation_required"
    assert node.params == {"name_or_model": "A100", "price": 25.5}
    service._run_workflow_with_state_updates.assert_not_called()


def test_invalid_missing_integer_does_not_mutate_node():
    from app.application.workflow.clarification_fields import resolve_missing_field

    node = WorkflowNode(node_id="d", tool_id="products", action="delete", params={}, risk="high")
    item = {"reason": "missing_required", "field": "id", "missing_fields": ["id"]}
    for value in ("abc", "true", "1.5", "{}", ""):
        assert resolve_missing_field(node, item, value) is None
    assert node.params == {}
    assert resolve_missing_field(node, item, "42") == {"id": 42}


def test_multiple_required_fields_wait_until_all_are_valid():
    from app.application.workflow.clarification_node import needs_clarification
    from app.services.tools_execution.registry import get_workflow_tool_registry

    node = WorkflowNode(
        node_id="create", tool_id="finance", action="create_transaction", params={}, risk="medium"
    )
    plan = PlanGraph(plan_id="p", intent="finance", nodes=[node])
    item = needs_clarification(plan, get_workflow_tool_registry())[0]
    pending = {
        "kind": "clarification",
        "plan": plan,
        "target_node_id": "create",
        "clarify_node_id": "clarify",
        "runtime_context": {},
        "clarification": item,
    }
    service = SimpleNamespace(
        _pending_workflows={"u": pending},
        approval_service=Mock(),
        _persist_plan_state=Mock(),
        _run_workflow_with_state_updates=Mock(side_effect=AssertionError("must not execute")),
    )
    service.approval_service.get_approval_required_nodes.return_value = [node]
    method = _AIChatApplicationServicePart03Mixin._continue_after_clarification
    assert method(service, "u", pending, "revenue") is None
    assert node.params == {"transaction_type": "revenue"}
    assert pending["clarification"]["missing_fields"] == ["amount"]
    service.approval_service.get_approval_required_nodes.assert_not_called()
    assert method(service, "u", pending, "invalid") is None
    assert node.params == {"transaction_type": "revenue"}
    result = method(service, "u", pending, "125.5")
    assert result["data"]["action"] == "workflow_confirmation_required"
    assert node.params == {"transaction_type": "revenue", "amount": 125.5}
    service._run_workflow_with_state_updates.assert_not_called()
