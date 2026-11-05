from __future__ import annotations

import logging

from app.application.ai_chat.planned_workflow_dispatch import _log_price_list_result


def test_price_list_result_log_contains_only_aggregate_fields(caplog) -> None:
    private_customer = "private-customer-fixture"
    private_path = "/private/customer/fixture.docx"
    with caplog.at_level(logging.INFO, logger="app.application.ai_chat.planned_workflow_dispatch"):
        _log_price_list_result(
            {
                "success": True,
                "customer_name": private_customer,
                "file_path": private_path,
                "products": [{"name": "private-product-fixture"}],
            }
        )

    assert "success=True" in caplog.text
    assert "product_count=1" in caplog.text
    assert private_customer not in caplog.text
    assert private_path not in caplog.text
    assert "private-product-fixture" not in caplog.text
