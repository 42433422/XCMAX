"""Product creation requires identity, not an unrelated customer name."""

from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.tool_spec import get_tool_action_spec, validate_tool_call
from app.services.tools_workflow_registered_part01_part01 import _registered_router_products


@pytest.mark.parametrize(
    "extra,unit", [({}, "个"), ({"unit": "箱"}, "箱"), ({"unit_name": "桶"}, "桶")]
)
def test_create_without_customer_matches_actual_dispatch_payload(extra, unit):
    params = {"name_or_model": "A100", "model_number": "A100", "price": 25.5, **extra}
    spec = get_tool_action_spec("products", "create")
    assert spec.required_params == ["name_or_model"]
    assert spec.input_schema["required"] == ["name_or_model"]
    assert validate_tool_call("products", "create", params).ok
    service = Mock()
    service.create_product.return_value = {"success": True, "data": {"id": 1}}
    with patch("app.services.get_products_service", return_value=service):
        result = _registered_router_products("create", params, {}, "pro_default", "")
    assert result["success"]
    payload = service.create_product.call_args.args[0]
    assert payload["model_number"] == "A100" and payload["price"] == 25.5
    assert payload["unit"] == unit
    assert "customer_name" not in payload


def test_product_identity_still_required():
    assert not validate_tool_call("products", "create", {"price": 25.5}).ok
