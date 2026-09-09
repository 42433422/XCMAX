import json
from unittest.mock import Mock, patch

from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_model_prompt_exposes_receipt_query_parameters():
    service = Mock()
    service.get_context.return_value = None
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=service):
        planner = LLMWorkflowPlanner()
    with patch("app.application.workflow.planner.request_planner_completion", return_value=None) as completion:
        planner._plan_with_llm("test", "user", "核验刚才的库存流水", get_workflow_tool_registry(), {})
    prompt = json.loads(completion.call_args.kwargs["messages"][1]["content"])
    tools = prompt["tool_registry"]
    inventory = next(tool for tool in tools if tool["tool_id"] == "inventory")
    query = next(action for action in inventory["actions"] if action["action"] == "query_transactions")
    assert "transaction_id" in query["optional_params"]
    assert "真实 transaction_id" in query["description"]
    assert query["required_params"] == []
    assert query["risk"] == "low" and query["idempotent"] is True
