from unittest.mock import Mock, patch

import pytest

from app.services.tools_workflow_registered_part01_part02 import _registered_router_sales


@pytest.mark.parametrize(
    "source",
    [
        None,
        {"success": False, "data": {"id": 7}},
        {"success": True, "data": {"id": True}},
        {"success": True, "data": {"id": -1}},
    ],
)
def test_invalid_prior_order_cannot_be_confirmed(source):
    service = Mock()
    with patch("app.application.sales_app_service.SalesAppService", return_value=service):
        result = _registered_router_sales(
            "confirm", {"order_node_id": "quote"}, {"node_outputs": {"quote": source}}, "normal", ""
        )
    assert not result["success"]
    service.confirm.assert_not_called()


def test_confirm_resolves_prior_order_and_rejects_conflicting_id():
    service = Mock()
    service.confirm.return_value = {"success": True}
    context = {"node_outputs": {"quote": {"success": True, "data": {"id": 7}}}}
    with patch("app.application.sales_app_service.SalesAppService", return_value=service):
        result = _registered_router_sales(
            "confirm", {"order_node_id": "quote"}, context, "normal", ""
        )
        assert result["success"]
        service.confirm.assert_called_once_with(7)
        service.reset_mock()
        conflict = _registered_router_sales(
            "confirm", {"order_node_id": "quote", "order_id": 8}, context, "normal", ""
        )
    assert not conflict["success"]
    service.confirm.assert_not_called()


def test_reference_confirmation_is_registered_and_requires_source():
    from app.application.agent_orchestrator.tool_spec import validate_tool_call
    from app.services.tools_execution.registry import get_workflow_tool_registry

    action = get_workflow_tool_registry()["sales"]["actions"]["confirm_from_result"]
    assert action["required_params"] == ["order_node_id"]
    assert action["risk"] == "medium"
    assert validate_tool_call("sales", "confirm_from_result", {"order_node_id": "quote"}).ok
    assert not validate_tool_call("sales", "confirm_from_result", {}).ok
    service = Mock()
    with patch("app.application.sales_app_service.SalesAppService", return_value=service):
        result = _registered_router_sales("confirm_from_result", {"order_id": 7}, {}, "normal", "")
    assert not result["success"]
    service.confirm.assert_not_called()


def test_quote_then_confirm_updates_only_created_order(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.sales_app_service import SalesAppService
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.sales_order_planning import sales_order_nodes
    from app.application.workflow.types import PlanGraph
    from app.db.base import Base
    from app.db.models import Customer, Product, SalesOrder
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'orders.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Customer(id=1, tenant_id=1, customer_name="星光"))
        db.add(Product(id=1, tenant_id=1, name="A100", model_number="A100", price=25.5))
        db.add(SalesOrder(id=10, tenant_id=2, order_no="other", state="quote", total_amount=99))

    with factory.begin() as db, tenant_scope(1):

        @contextmanager
        def database():
            yield db

        monkeypatch.setattr("app.application.workflow.sales_order_planning.get_db", database)
        nodes = sales_order_nodes("给客户星光下订单，产品A100，数量10")
        actual = SalesAppService()
        adapter = Mock()
        adapter.quote.side_effect = lambda params: actual.quote(params, db=db)
        adapter.confirm.side_effect = lambda ident: actual.confirm(ident, db=db)

        def dispatch(tool_id, action, params):
            return _registered_router_sales(
                action, params, params["_runtime_context"], "normal", ""
            )

        with patch("app.application.sales_app_service.SalesAppService", return_value=adapter):
            result = WorkflowEngine(dispatch).run(
                PlanGraph(plan_id="order", intent="sales_order", nodes=nodes)
            )
        assert result.success, result.message
        created = db.query(SalesOrder).one()
        assert created.state == "confirmed" and float(created.total_amount) == 255
        assert created.customer_id == 1
        adapter.confirm.assert_called_once_with(created.id)
    with factory() as db, tenant_scope(2):
        other = db.get(SalesOrder, 10)
        assert other.state == "quote" and float(other.total_amount) == 99
    engine.dispose()


def test_default_session_confirmation_is_committed(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.sales_app_service import SalesAppService
    from app.db.base import Base
    from app.db.models import Customer, Product, SalesOrder
    from app.infrastructure.tenant_scope import tenant_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'committed.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Customer(id=1, tenant_id=1, customer_name="星光"))
        db.add(Product(id=1, tenant_id=1, name="A100"))
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with tenant_scope(1):
        service = SalesAppService()
        quote = service.quote(
            {"customer_id": 1, "items": [{"product_id": 1, "quantity": 10, "unit_price": 25.5}]}
        )
        assert quote["success"]
        ident = quote["data"]["id"]
        confirmed = service.confirm(ident)
        assert confirmed["success"]
        with factory() as fresh:
            order = fresh.get(SalesOrder, ident)
            assert order.state == "confirmed"
            assert float(order.total_amount) == 255
    engine.dispose()
