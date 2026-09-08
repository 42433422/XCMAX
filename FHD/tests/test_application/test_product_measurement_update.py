from unittest.mock import Mock, patch

import pytest

from app.services.tools_workflow_registered import _registered_router_products


@pytest.mark.parametrize("field", ["measure_unit", "unit_name", "measurement_unit"])
def test_ai_measurement_update_preserves_legacy_customer_column(field):
    service = Mock()
    service.update_product.return_value = {"success": True}
    with patch("app.services.get_products_service", return_value=service):
        result = _registered_router_products("update", {"id": 1, field: "桶"}, {}, "normal", "")
    assert result["success"]
    service.update_product.assert_called_once_with(1, {"measurement_unit": "桶"})


def test_ai_customer_update_does_not_replace_unit_with_default():
    service = Mock()
    with patch("app.services.get_products_service", return_value=service):
        result = _registered_router_products(
            "update", {"id": 1, "unit_name": "客户公司"}, {}, "normal", ""
        )
    assert result["error_code"] == "customer_product_link_unsupported"
    service.update_product.assert_not_called()
