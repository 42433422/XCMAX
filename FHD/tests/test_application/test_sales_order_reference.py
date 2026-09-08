from unittest.mock import Mock, patch

import pytest

from app.services.tools_workflow_registered_part01_part02 import _registered_router_sales


@pytest.mark.parametrize(
    "source",
    [
        None,
        {"success": False, "data": {"id": 7}},
        {"success": True, "data": {"id": True}},
        {"success": True, "data": {"id": -1}},
    ],
)
def test_invalid_prior_order_cannot_be_confirmed(source):
    service = Mock()
    with patch("app.application.sales_app_service.SalesAppService", return_value=service):
        result = _registered_router_sales(
            "confirm", {"order_node_id": "quote"}, {"node_outputs": {"quote": source}}, "normal", ""
        )
    assert not result["success"]
    service.confirm.assert_not_called()


def test_confirm_resolves_prior_order_and_rejects_conflicting_id():
    service = Mock()
    service.confirm.return_value = {"success": True}
    context = {"node_outputs": {"quote": {"success": True, "data": {"id": 7}}}}
    with patch("app.application.sales_app_service.SalesAppService", return_value=service):
        result = _registered_router_sales(
            "confirm", {"order_node_id": "quote"}, context, "normal", ""
        )
        assert result["success"]
        service.confirm.assert_called_once_with(7)
        service.reset_mock()
        conflict = _registered_router_sales(
            "confirm", {"order_node_id": "quote", "order_id": 8}, context, "normal", ""
        )
    assert not conflict["success"]
    service.confirm.assert_not_called()


def test_reference_confirmation_is_registered_and_requires_source():
    from app.application.agent_orchestrator.tool_spec import validate_tool_call
    from app.services.tools_execution.registry import get_workflow_tool_registry

    action = get_workflow_tool_registry()["sales"]["actions"]["confirm_from_result"]
    assert action["required_params"] == ["order_node_id"]
    assert action["risk"] == "medium"
    assert validate_tool_call("sales", "confirm_from_result", {"order_node_id": "quote"}).ok
    assert not validate_tool_call("sales", "confirm_from_result", {}).ok
    service = Mock()
    with patch("app.application.sales_app_service.SalesAppService", return_value=service):
        result = _registered_router_sales("confirm_from_result", {"order_id": 7}, {}, "normal", "")
    assert not result["success"]
    service.confirm.assert_not_called()
