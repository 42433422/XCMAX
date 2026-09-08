from unittest.mock import Mock, patch

from app.services.tools_workflow_registered import execute_registered_workflow_tool


def test_product_creation_does_not_silently_drop_customer_unit():
    service = Mock()
    with patch("app.services.get_products_service", return_value=service):
        result = execute_registered_workflow_tool(
            "products",
            "create",
            {"name_or_model": "P100", "unit_name": "公司A", "unit": "桶"},
        )
    assert result["success"] is False
    assert result["error_code"] == "customer_product_link_unsupported"
    service.create_product.assert_not_called()
