from unittest.mock import patch

import pytest

from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_execution.order_parser import _parse_order_text
from app.services.tools_execution.registry import get_workflow_tool_registry


def plan_message(message):
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        return LLMWorkflowPlanner()._fallback_plan(
            "shipment", message, get_workflow_tool_registry()
        )


def test_full_order_preserves_customer_model_spec_quantity():
    plan = plan_message("打印 七彩乐园 的发货单，编号9803，规格12，一共3桶")
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("shipment_orders", "generate")]
    node = plan.nodes[0]
    assert node.params == {
        "unit_name": "七彩乐园",
        "products": [{"name": "", "model_number": "9803", "quantity_tins": 3, "tin_spec": 12.0}],
    }
    assert node.risk == "high" and not node.idempotent


def test_missing_order_requires_clarification():
    plan = plan_message("打个发货单")
    assert [(n.tool_id, n.action) for n in plan.nodes] == [
        ("clarify", "ask"),
        ("shipment_orders", "generate"),
    ]
    assert plan.nodes[1].params == {}


def test_strict_parser_does_not_invent_quantity_or_spec(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    result = _parse_order_text("星光 新商品", allow_defaults=False)
    assert not result["success"]


@pytest.mark.parametrize(
    "message", ["查询发货单", "删除发货单", "不要打印发货单", "预览发货单模板"]
)
def test_non_generation_requests_do_not_generate(message):
    assert not any(
        n.tool_id == "shipment_orders" and n.action == "generate"
        for n in plan_message(message).nodes
    )
