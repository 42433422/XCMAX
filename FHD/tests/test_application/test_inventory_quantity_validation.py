from unittest.mock import patch

import pytest

from app.services.inventory_service import InventoryService


@pytest.mark.parametrize(
    "quantity", [0, -1, float("nan"), float("inf"), -float("inf"), True, None, "bad"]
)
def test_invalid_inbound_quantity_never_opens_database(quantity):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_in(product_id=1, warehouse_id=1, quantity=quantity)
    assert not result["success"]
    database.assert_not_called()
