"""Direct customer creation keeps contact slots and write risk metadata."""

from unittest.mock import patch

import pytest

from app.application.chat_tool_intent import looks_like_business_db_write
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.types import validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry


@pytest.mark.parametrize(
    "text",
    [
        "新增客户 蓝天科技，联系人张三，电话13800000001",
        "添加客户：蓝天科技，联系人：张三，电话：13800000001",
        "请帮我新增客户蓝天科技，联系人张三，电话13800000001",
    ],
)
def test_direct_creation_keeps_contact_slots(text):
    assert looks_like_business_db_write(text)
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", text, get_workflow_tool_registry())
    assert validate_plan_graph(plan) is None
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("business_db", "write")]
    node = plan.nodes[0]
    assert node.params["entity"] == "customers"
    assert node.params["payload"]["unit_name"] == "蓝天科技"
    assert node.params["payload"]["contact_person"] == "张三"
    assert node.params["payload"]["contact_phone"] == "13800000001"
    assert node.risk == "medium"


@pytest.mark.parametrize("text", ["不要新增客户", "如何添加客户", "新增产品", "给客户添加产品"])
def test_other_requests_do_not_become_direct_customer_writes(text):
    assert not looks_like_business_db_write(text)
