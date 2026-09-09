from unittest.mock import Mock, patch

import pytest

from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_workflow_registered import execute_registered_workflow_tool


@pytest.mark.parametrize("message", [
    "预览送货单模板", "看看发货单的模板", "模板预览",
    "出货单长什么样，给我看看版式", "看看送货单版式",
])
def test_preview_reads_templates_instead_of_creating_shipment(message):
    assert route_normal_mode_message(message)["intent"] == "template_preview"
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", message, {"template_preview": {}, "shipment_orders": {}})
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("template_preview", "query")]
    service = Mock()
    service.get_templates.return_value = {"success": True, "data": [{"id": 7, "name": "标准送货单"}]}
    with patch("app.application.get_template_app_service", return_value=service):
        node = plan.nodes[0]
        result = execute_registered_workflow_tool(node.tool_id, node.action, node.params)
    assert result["data"][0]["id"] == 7
    service.get_templates.assert_called_once_with()
    assert len(service.mock_calls) == 1


def test_denied_preview_still_requires_clarification():
    assert route_normal_mode_message("不要打印，看看发货单版式")["intent"] == "clarify"


def test_ordinary_chat_uses_actual_template_application_contract():
    from app.application.normal_chat_dispatch import try_normal_slot_read_payload
    from app.application.template_app_service import TemplateApplicationService

    repository = Mock()
    repository.list_templates.return_value = [{"id": 7, "name": "客户送货单", "fields": []}]
    service = TemplateApplicationService(repository)
    with patch("app.application.get_template_app_service", return_value=service):
        result = try_normal_slot_read_payload("看看发货单的模板")
    assert result["success"]
    assert "客户送货单" in result["response"]
    assert any(row["id"] == 7 for row in result["data"]["templates"])
    assert result["data"]["intent"] == "template_preview"
    repository.list_templates.assert_called_once_with()
    assert len(repository.mock_calls) == 1


@pytest.mark.parametrize("tool_result", [
    {"success": False, "message": "database unavailable"},
    {"success": True},
    {"templates": None},
])
def test_template_read_failure_is_not_empty_success(tool_result):
    from app.application.normal_chat_dispatch import try_normal_slot_read_payload

    with patch(
        "app.application.template_query_response.execute_registered_workflow_tool",
        return_value=tool_result,
    ):
        result = try_normal_slot_read_payload("模板预览")
    assert result["success"] is False
    assert "无法读取" in result["response"]
