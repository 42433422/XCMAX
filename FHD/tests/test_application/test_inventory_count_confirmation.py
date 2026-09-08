from unittest.mock import patch

import pytest

from app.services.inventory_service import InventoryService


@pytest.mark.parametrize("confirmed", ["false", "true", 1, 0, None, [], {}])
def test_count_requires_boolean_confirmation_before_database(confirmed):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_count(1, 1, 3, confirmed=confirmed)
    assert not result["success"]
    database.assert_not_called()


@pytest.mark.parametrize("quantity", [True, -1, None, float("nan"), float("inf")])
def test_count_rejects_invalid_quantity_before_database(quantity):
    with patch("app.services.inventory_service.get_db") as database:
        result = InventoryService().inventory_count(1, 1, quantity, confirmed=True)
    assert not result["success"]
    database.assert_not_called()


def test_ai_count_string_false_does_not_become_confirmation():
    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    with patch("app.services.inventory_service.get_db") as database:
        result = _registered_router_inventory(
            "inventory_count",
            {"product_id": 1, "warehouse_id": 1, "actual_quantity": "3", "confirmed": "false"},
            {},
            "normal",
            "",
        )
    assert not result["success"]
    database.assert_not_called()
