from unittest.mock import Mock, patch

import pytest

from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.printer_query_response import build_printer_query_response
from app.application.workflow.planner import LLMWorkflowPlanner


@pytest.mark.parametrize("message", ["打印机列表", "现在连的哪台打印机", "看看有哪些打印机"])
def test_printer_query_reaches_registered_capability(message):
    assert route_normal_mode_message(message)["intent"] == "printer_list"
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", message, {"printer_list": {}})
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("printer_list", "query")]
    service = Mock()
    service.get_printer_config.return_value = {
        "success": True,
        "printers": ["Office"],
        "default_printer": "Office",
    }
    with patch("app.services.get_system_service", return_value=service):
        response = build_printer_query_response()
    assert response["success"]
    assert response["data"]["printers"] == ["Office"]
    assert "Office" in response["response"]
    service.get_printer_config.assert_called_once_with()
    service.set_default_printer.assert_not_called()


def test_printer_query_failure_is_not_reported_as_empty_success():
    service = Mock()
    service.get_printer_config.return_value = {"success": False, "message": "unavailable"}
    with patch("app.services.get_system_service", return_value=service):
        response = build_printer_query_response()
    assert not response["success"]
    assert "未能读取" in response["response"]
