"""Persisted task identity must reach real business repositories outside HTTP."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.customer_app_service import CustomerApplicationService
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope


@pytest.fixture
def business_store(monkeypatch):
    engine = create_engine("sqlite://")
    PurchaseUnit.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    for tenant, name in [(7, "账号七客户"), (8, "账号八客户")]:
        with tenant_scope(tenant), sessions() as session:
            session.add(PurchaseUnit(unit_name=name, is_active=True))
            session.commit()
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", sessions)
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: service)
    yield sessions
    engine.dispose()


def test_background_customer_query_reads_only_the_persisted_account(business_store):
    executor = AgentToolExecutor()
    step = AgentStep(node_id="customers", tool_id="customers", action="query", params={})
    # Simulate a worker with no originating request. The repository must receive
    # the saved task tenant rather than an ambient desktop tenant or no tenant.
    with tenant_scope(None):
        result = executor.execute(step, runtime_context={"tenant_id": "7"})
        assert current_tenant_id() is None
    assert result["success"] is True
    assert [row["customer_name"] for row in result["data"]] == ["账号七客户"]
    with tenant_scope(7):
        other = executor.execute(step, runtime_context={"tenant_id": "8"})
        assert current_tenant_id() == 7
    assert [row["customer_name"] for row in other["data"]] == ["账号八客户"]


def test_background_customer_update_persists_and_cannot_change_another_account(business_store):
    with tenant_scope(7), business_store() as session:
        customer_id = session.query(PurchaseUnit).one().id
    executor = AgentToolExecutor()
    step = AgentStep(
        node_id="update",
        tool_id="customers",
        action="update",
        params={"id": customer_id, "contact_person": "任务更新"},
    )
    with tenant_scope(None):
        result = executor.execute(step, runtime_context={"tenant_id": "7"})
        assert result["success"] is True
        rejected = executor.execute(step, runtime_context={"tenant_id": "8"})
        assert rejected["success"] is False
    with tenant_scope(7), business_store() as session:
        assert session.query(PurchaseUnit).one().contact_person == "任务更新"
    with tenant_scope(8), business_store() as session:
        assert session.query(PurchaseUnit).one().contact_person is None


@pytest.mark.parametrize("tenant", [True, 0, -1, 7.5, "wrong-account"])
def test_business_task_rejects_invalid_tenant_before_repository(tenant):
    step = AgentStep(node_id="customers", tool_id="customers", action="query", params={})
    result = AgentToolExecutor().execute(step, runtime_context={"tenant_id": tenant})
    assert result["error_code"] == "invalid_tenant_context"
