import pytest

from app.application.workflow.clarification_fields import resolve_missing_field
from app.application.workflow.types import WorkflowNode


def test_quote_items_answer_is_validated_without_mutating_pending_node():
    node = WorkflowNode(
        node_id="quote", tool_id="sales", action="quote", params={"customer_id": 101}, risk="medium"
    )
    item = {"reason": "missing_required", "field": "items", "missing_fields": ["items"]}
    answer = '[{"product_id":201,"quantity":2,"unit_price":25.5}]'
    assert resolve_missing_field(node, item, answer) == {
        "items": [{"product_id": 201, "quantity": 2, "unit_price": 25.5}]
    }
    assert node.params == {"customer_id": 101}


@pytest.mark.parametrize(
    "answer",
    [
        "{}",
        '"items"',
        "not json",
        "[]",
        "[{}]",
        '[{"quantity":2}]',
        '[{"quantity":true,"unit_price":5}]',
        '[{"quantity":NaN}]',
        '[{"quantity":1e999}]',
    ],
)
def test_invalid_structured_answer_keeps_pending_params(answer):
    node = WorkflowNode(
        node_id="quote", tool_id="sales", action="quote", params={"customer_id": 101}, risk="medium"
    )
    item = {"reason": "missing_required", "field": "items", "missing_fields": ["items"]}
    assert resolve_missing_field(node, item, answer) is None
    assert node.params == {"customer_id": 101}
