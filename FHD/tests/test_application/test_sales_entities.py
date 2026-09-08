from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.workflow.sales_entities import sales_entity_candidates
from app.db.base import Base
from app.db.models import Customer, Product
from app.infrastructure.tenant_scope import tenant_scope


def test_sales_candidates_are_exact_tenant_bound_and_read_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add_all(
            [
                Customer(id=1, tenant_id=1, customer_name="星光"),
                Customer(id=2, tenant_id=2, customer_name="星光"),
                Product(id=1, tenant_id=1, name="涂料", model_number="A100", price=25.5),
                Product(id=2, tenant_id=2, name="A100"),
            ]
        )
    with tenant_scope(1), factory() as db:
        result = sales_entity_candidates(db, customer_name="星光", product_name="A100")
        assert result["customer_unique"] and result["product_unique"]
        assert [c["id"] for c in result["customer_candidates"]] == [1]
        assert [p["id"] for p in result["product_candidates"]] == [1]
        from contextlib import contextmanager
        from unittest.mock import patch
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry

        @contextmanager
        def planning_db():
            yield db

        monkeypatch.setattr("app.application.workflow.sales_quote_planning.get_db", planning_db)
        with patch(
            "app.application.workflow.planner.get_ai_conversation_service", return_value=None
        ):
            planner = LLMWorkflowPlanner()
        plan = planner._fallback_plan(
            "quote", "给星光报价，产品A100，数量2，单价25.5", get_workflow_tool_registry()
        )
        assert [(n.tool_id, n.action) for n in plan.nodes] == [("sales", "quote")]
        assert plan.nodes[0].params == {
            "customer_id": 1,
            "items": [{"product_id": 1, "quantity": 2.0, "unit_price": 25.5, "unit": "个"}],
        }
        assert not plan.nodes[0].idempotent
        missing = sales_entity_candidates(db, customer_name="星", product_name="A10")
        assert missing["customer_candidates"] == missing["product_candidates"] == []
        assert db.query(Customer).count() == db.query(Product).count() == 1
        db.add(Customer(id=3, tenant_id=1, customer_name="星光"))
        db.flush()
        ambiguous = sales_entity_candidates(db, customer_name="星光", product_name="A100")
        assert not ambiguous["customer_unique"]
        assert [c["id"] for c in ambiguous["customer_candidates"]] == [1, 3]
        db.rollback()
    engine.dispose()
