"""Customer-query slots and fallback planning through a real tenant-scoped service."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.customer_app_service import CustomerApplicationService
from app.application.customer_query_intent import customer_query_slots
from app.application.workflow.planner import LLMWorkflowPlanner, _execute_customers_tool
from app.application.workflow.types import validate_plan_graph
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_scope
from app.services.tools_execution.registry import get_workflow_tool_registry


@pytest.mark.parametrize(
    "text, keyword",
    [
        ("客户列表", ""),
        ("客户有哪些", ""),
        ("查询甲公司的客户", "甲公司"),
        ("查询客户「星光产品公司」的信息", "星光产品公司"),
        ("查询所有客户", ""),
        ("你好，客户列表", ""),
        ("查一下客户 星光贸易 的信息", "星光贸易"),
        ("查询客户「星 光贸易」的资料", "星 光贸易"),
    ],
)
def test_query_slots(text, keyword):
    assert customer_query_slots(text) == {"keyword": keyword}


@pytest.mark.parametrize(
    "text",
    [
        "新增客户星光",
        "不要查客户",
        "给客户星光下订单",
        "客户星光的产品",
        "查询删除甲公司的客户",
        "查询甲公司，新增乙公司的客户",
    ],
)
def test_other_actions_are_not_customer_queries(text):
    assert customer_query_slots(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [("客户列表", [1, 2]), ("查一下客户 星光贸易 的信息", [1])],
)
def test_fallback_query_returns_matching_tenant_records(tmp_path, monkeypatch, text, expected):
    engine = create_engine(f"sqlite:///{tmp_path / 'customers.sqlite'}")
    factory = sessionmaker(bind=engine)
    PurchaseUnit.__table__.create(engine)
    with factory.begin() as db:
        db.add_all(
            [
                PurchaseUnit(id=1, tenant_id=7, unit_name="星光贸易", is_active=True),
                PurchaseUnit(id=2, tenant_id=7, unit_name="蓝天科技", is_active=True),
                PurchaseUnit(id=3, tenant_id=8, unit_name="星光贸易", is_active=True),
            ]
        )
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", lambda: factory())
    monkeypatch.setattr("app.bootstrap.get_customer_app_service", lambda: service)
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    with tenant_scope(7):
        plan = planner._fallback_plan("query-test", text, get_workflow_tool_registry())
        assert validate_plan_graph(plan) is None
        assert [(node.tool_id, node.action) for node in plan.nodes] == [("customers", "query")]
        result = _execute_customers_tool(plan.nodes[0].params)
        assert result["success"], result
        assert sorted(row["id"] for row in result["data"]) == sorted(expected)
    for tenant_id, count in ((7, 2), (8, 1)):
        with tenant_scope(tenant_id), factory() as db:
            assert db.query(PurchaseUnit).count() == count
    engine.dispose()
