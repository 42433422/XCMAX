from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.workflow.sales_entities import sales_entity_candidates
from app.db.base import Base
from app.db.models import Customer, Product, SalesOrder, SalesOrderItem
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
        monkeypatch.setattr("app.application.workflow.sales_order_planning.get_db", planning_db)
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
        from app.application.sales_app_service import SalesAppService

        incomplete = planner._fallback_plan(
            "unpriced", "给星光的产品A100报个价", get_workflow_tool_registry()
        )
        assert [(n.tool_id, n.action) for n in incomplete.nodes] == [
            ("clarify", "ask"),
            ("sales", "quote"),
        ]
        assert incomplete.nodes[1].params == {
            "customer_id": 1,
            "_quote_product": {"product_id": 1, "unit": "个"},
        }
        from app.application.workflow.clarification_fields import resolve_missing_field

        filled = resolve_missing_field(
            incomplete.nodes[1],
            {"reason": "missing_required", "field": "items", "missing_fields": ["items"]},
            '[{"quantity": 2, "unit_price": 25.5}]',
        )
        assert filled == {
            "items": [{"product_id": 1, "unit": "个", "quantity": 2, "unit_price": 25.5}]
        }
        assert "A100" in incomplete.nodes[1].description
        assert db.query(SalesOrder).count() == 0
        assert db.query(SalesOrderItem).count() == 0
        order_plan = planner._fallback_plan(
            "order", "给客户星光下订单，产品A100，数量10", get_workflow_tool_registry()
        )
        assert [(n.tool_id, n.action) for n in order_plan.nodes] == [
            ("sales", "quote"),
            ("sales", "confirm_from_result"),
        ]
        assert order_plan.nodes[0].params["items"] == [
            {"product_id": 1, "unit": "个", "quantity": 10.0, "unit_price": 25.5}
        ]
        assert order_plan.nodes[1].depends_on == [order_plan.nodes[0].node_id]
        assert db.query(SalesOrder).count() == 0
        saved = SalesAppService().quote(plan.nodes[0].params, db=db)
        assert saved["success"], saved
        order = db.query(SalesOrder).one()
        line = db.query(SalesOrderItem).one()
        assert order.customer_id == 1 and order.state == "quote"
        assert line.product_id == 1 and float(line.quantity) == 2
        assert float(line.unit_price) == 25.5 and float(order.total_amount) == 51

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


def test_invalid_quote_numbers_do_not_query_entities():
    from unittest.mock import patch

    from app.application.workflow.sales_quote_planning import explicit_sales_quote_node

    with patch("app.application.workflow.sales_quote_planning.get_db") as db:
        for quantity, price in [("0", "25"), ("9" * 400, "25"), ("1", "9" * 400)]:
            assert (
                explicit_sales_quote_node(f"给星光报价，产品A100，数量{quantity}，单价{price}")
                is None
            )
        db.assert_not_called()
