from unittest.mock import Mock

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import WorkflowNode
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_quote_failure_does_not_retry_in_plan_or_agentic_dispatch():
    registry = get_workflow_tool_registry()
    metadata = registry["sales"]["actions"]["quote"]
    dispatch = Mock(return_value={"success": False, "message": "connection lost after request"})
    engine = WorkflowEngine(tool_dispatcher=dispatch)
    params = {"customer_id": 1, "items": [{"product_id": 1, "quantity": 2, "unit_price": 25}]}
    node = WorkflowNode(
        node_id="quote",
        tool_id="sales",
        action="quote",
        params=params,
        risk=metadata["risk"],
        idempotent=metadata["idempotent"],
    )
    result = engine._run_node(node, {}, max_retries=3)
    assert not result.success and result.retries == 0
    assert dispatch.call_count == 1
    dispatch.reset_mock()
    retryable = engine._agentic_tool_allows_auto_retry(registry, "sales", "quote")
    assert retryable is False
    result = engine._run_single_tool(
        tool_id="sales",
        action="quote",
        params=params,
        runtime_context={},
        max_retries=3,
        retryable=retryable,
    )
    assert not result.success and result.retries == 0
    assert dispatch.call_count == 1
