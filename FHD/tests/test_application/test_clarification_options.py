import pytest

from app.application.workflow.clarification_fields import resolve_missing_field
from app.application.workflow.clarification_node import needs_clarification
from app.application.workflow.clarification_options import field_options
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.services.tools_execution.registry import get_workflow_tool_registry


@pytest.mark.parametrize(
    "label,canonical", field_options("finance", "create_transaction", "transaction_type").items()
)
def test_displayed_option_resolves_to_valid_protocol_enum(label, canonical):
    node = WorkflowNode(
        node_id="n", tool_id="finance", action="create_transaction", params={}, risk="medium"
    )
    item = needs_clarification(
        PlanGraph(plan_id="p", intent="finance", nodes=[node]), get_workflow_tool_registry()
    )[0]
    assert label in item["question"]
    assert resolve_missing_field(node, item, label) == {"transaction_type": canonical}
    assert resolve_missing_field(node, item, canonical) == {"transaction_type": canonical}
    assert resolve_missing_field(node, item, "不确定") is None
    assert node.params == {}


def test_option_aliases_are_scoped_to_exact_tool_action_and_field():
    assert field_options("products", "create", "name_or_model") == {}
    assert field_options("finance", "create_transaction", "description") == {}
