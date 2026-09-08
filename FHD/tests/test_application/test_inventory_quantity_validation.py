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
    from app.db.models import (
        InventoryLedger,
        InventoryTransaction,
        Product,
        StorageLocation,
        Warehouse,
    )
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'inventory.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Product(id=1, tenant_id=1, name="A100"))
        db.add(Warehouse(id=2, tenant_id=2, name="其他租户", code="other"))
        db.add(Warehouse(id=3, tenant_id=1, name="本仓", code="own"))
        db.add(Warehouse(id=4, tenant_id=1, name="另一仓", code="second"))
        db.flush()
        db.add(StorageLocation(id=4, tenant_id=1, warehouse_id=4, code="wrong"))
        db.add(StorageLocation(id=5, tenant_id=1, warehouse_id=3, code="A"))
        db.add(StorageLocation(id=6, tenant_id=1, warehouse_id=3, code="B"))
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with tenant_scope(1):
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry

        with patch(
            "app.application.workflow.planner.get_ai_conversation_service", return_value=None
        ):
            planner = LLMWorkflowPlanner()
        plan = planner._fallback_plan(
            "inbound", "产品 A100 入库 50 件", get_workflow_tool_registry()
        )
        assert [(node.tool_id, node.action) for node in plan.nodes] == [
            ("clarify", "ask"),
            ("inventory", "stock_in"),
        ]
        assert plan.nodes[1].params == {"product_id": 1, "quantity": 50.0, "requested_unit": "件"}
        from app.application.workflow.clarification_fields import resolve_missing_field

        item = {
            "reason": "missing_required",
            "field": "warehouse_id",
            "missing_fields": ["warehouse_id"],
        }
        assert resolve_missing_field(plan.nodes[1], item, "3") == {"warehouse_id": 3}
        for answer in ("true", "3.5", "仓库", "{}"):
            assert resolve_missing_field(plan.nodes[1], item, answer) is None
        for warehouse_id in (2, 999):
            result = InventoryService().inventory_in(
                product_id=1, warehouse_id=warehouse_id, quantity=5
            )
            assert not result["success"]
        for location_id in (4, 999):
            result = InventoryService().inventory_in(
                product_id=1, warehouse_id=3, location_id=location_id, quantity=5
            )
            assert not result["success"]
        with factory() as db:
            assert db.query(InventoryLedger).count() == 0
            assert db.query(InventoryTransaction).count() == 0
        from app.services.tools_workflow_registered_part01_part02 import (
            _registered_router_inventory,
        )

        mismatch = _registered_router_inventory(
            "stock_in",
            {"product_id": 1, "warehouse_id": 3, "quantity": 50, "requested_unit": "桶"},
            {},
            "normal",
            "",
        )
        assert not mismatch["success"]
        with factory() as db:
            assert db.query(InventoryLedger).count() == 0
            assert db.query(InventoryTransaction).count() == 0
        for location_id, quantity in [(5, 2), (6, 3), (5, 4)]:
            result = _registered_router_inventory(
                "stock_in",
                {
                    "product_id": 1,
                    "warehouse_id": 3,
                    "location_id": location_id,
                    "quantity": quantity,
                    "requested_unit": "个",
                },
                {},
                "normal",
                "",
            )
            assert result["success"], result
        with factory() as db:
            ledgers = db.query(InventoryLedger).order_by(InventoryLedger.location_id).all()
            assert [(row.location_id, float(row.quantity)) for row in ledgers] == [(5, 6), (6, 3)]
            transactions = db.query(InventoryTransaction).order_by(InventoryTransaction.id).all()
            assert [
                (row.location_id, float(row.before_quantity), float(row.after_quantity))
                for row in transactions
            ] == [(5, 0, 2), (6, 0, 3), (5, 2, 6)]
    engine.dispose()
