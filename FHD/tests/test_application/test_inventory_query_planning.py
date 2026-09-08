from contextlib import contextmanager
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.workflow.inventory_query_planning import inventory_query_node
from app.application.workflow.planner import LLMWorkflowPlanner
from app.db.base import Base
from app.db.models import InventoryLedger, Product, Warehouse
from app.infrastructure.tenant_scope import tenant_scope
from app.services.tools_execution.registry import get_workflow_tool_registry
from app.services.tools_workflow_registered_part01_part02 import _registered_router_reports


def test_inventory_query_filters_actual_stock_and_tenant(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        for ident, tenant, model, quantity in [
            (1, 1, "A100", 12),
            (2, 1, "B200", 99),
            (3, 2, "A100", 88),
        ]:
            db.add(Product(id=ident, tenant_id=tenant, name=model, model_number=model))
            db.add(Warehouse(id=ident, tenant_id=tenant, name=str(ident), code=str(ident)))
            db.flush()
            db.add(
                InventoryLedger(
                    product_id=ident,
                    warehouse_id=ident,
                    tenant_id=tenant,
                    quantity=quantity,
                    available_quantity=quantity,
                    reserved_quantity=0,
                )
            )

    @contextmanager
    def database():
        with factory() as db:
            yield db

    monkeypatch.setattr("app.services.report_service.get_db", database)
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("inventory", "查一下 A100 的库存", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("reports", "inventory_summary")]
    node = plan.nodes[0]
    with tenant_scope(1):
        result = _registered_router_reports(
            node.action, node.params, {}, "normal", "查一下 A100 的库存"
        )
    assert result["success"]
    assert [row["product_id"] for row in result["data"]] == [1]
    assert result["summary"] == {"total_products": 1, "total_quantity": 12, "total_available": 12}
    engine.dispose()


def test_inventory_query_rejects_negative_or_compound_commands():
    for message in (
        "不要查询 A100 的库存",
        "查询 A100 然后删除客户的库存",
        "查询 A100，B200 的库存",
    ):
        assert inventory_query_node(message) is None
