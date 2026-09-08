from unittest.mock import patch

import pytest

from app.application.sales_app_service import SalesAppService


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"quantity": 1},
        {"unit_price": 25},
        {"quantity": 0, "unit_price": 25},
        {"quantity": -1, "unit_price": 25},
        {"quantity": "NaN", "unit_price": 25},
        {"quantity": "Infinity", "unit_price": 25},
        {"quantity": 1, "unit_price": -1},
        {"quantity": 1, "unit_price": "NaN"},
        {"quantity": 1, "unit_price": "Infinity"},
    ],
)
def test_invalid_quote_rejected_before_database_access(item):
    with patch("app.application.sales_app_service.get_db") as db:
        result = SalesAppService().quote({"customer_id": 1, "items": [item]})
    assert result["success"] is False
    db.assert_not_called()
