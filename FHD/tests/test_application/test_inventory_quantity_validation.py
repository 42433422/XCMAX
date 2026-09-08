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


@pytest.mark.parametrize("quantity", [True, False, None, "bad", "NaN", "Infinity", 0, -1])
def test_tool_adapter_rejects_invalid_quantity_before_service(quantity):
    from unittest.mock import Mock

    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    service = Mock()
    with patch("app.application.inventory_app_service.InventoryAppService", return_value=service):
        result = _registered_router_inventory("stock_in", {"quantity": quantity}, {}, "normal", "")
    assert not result["success"]
    service.inventory_in.assert_not_called()


def test_tool_adapter_accepts_numeric_quantity_string():
    from unittest.mock import Mock

    from app.services.tools_workflow_registered_part01_part02 import _registered_router_inventory

    service = Mock()
    service.inventory_in.return_value = {"success": True}
    with patch("app.application.inventory_app_service.InventoryAppService", return_value=service):
        result = _registered_router_inventory(
            "stock_in", {"product_id": 1, "warehouse_id": 2, "quantity": "2.5"}, {}, "normal", ""
        )
    assert result["success"]
    assert service.inventory_in.call_args.kwargs["quantity"] == 2.5


def test_inbound_rejects_missing_and_other_tenant_warehouse(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    from app.db.models import InventoryLedger, InventoryTransaction, Product, Warehouse
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'inventory.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="A100"))
        db.add(Warehouse(id=2, tenant_id=2, name="其他租户", code="other"))
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with tenant_scope(1):
        for warehouse_id in (2, 999):
            result = InventoryService().inventory_in(
                product_id=1, warehouse_id=warehouse_id, quantity=5
            )
            assert not result["success"]
        with factory() as db:
            assert db.query(InventoryLedger).count() == 0
            assert db.query(InventoryTransaction).count() == 0
    engine.dispose()
