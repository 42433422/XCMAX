from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import compiled_chat_runtime as compiled_chat_runtime
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry
from tests.fixtures.planner_model import goal_review_response


def test_seed_demo_is_idempotent_and_visible_to_business_tools(tmp_path, monkeypatch) -> None:
    from app.application import onboarding_seed_app_service as service
    from app.db.db_base import Base
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase_unit import PurchaseUnit

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'onboarding.sqlite3'}")
    Base.metadata.create_all(
        engine,
        tables=[
            PurchaseUnit.__table__,
            UomCategory.__table__,
            UomUnit.__table__,
            Product.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def local_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(service, "get_db", local_db)

    first = service.seed_onboarding_demo_data(tenant_id=1, industry_id="通用")
    second = service.seed_onboarding_demo_data(tenant_id=1, industry_id="通用")

    assert first["customer"]["existing"] is False
    assert first["product"]["existing"] is False
    assert second["customer"]["existing"] is True
    assert second["product"]["existing"] is True
    with local_db() as db:
        customer = db.query(PurchaseUnit).filter(PurchaseUnit.tenant_id == 1).one()
        product = db.query(Product).filter(Product.tenant_id == 1).one()
        assert customer.unit_name == first["customer"]["name"]
        assert product.name == first["product"]["name"]


@pytest.mark.parametrize(
    ("source", "profile"), [(None, "normal"), (None, "pro_default"), ("pro", "pro_default")]
)
def test_seeded_first_order_from_chat_runs_real_tools_and_persists_after_confirmation(
    monkeypatch, compiled_chat_runtime, source, profile
) -> None:
    """Real host review, authenticated MCP child, approval and durable shipment."""
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.onboarding_seed_app_service import seed_onboarding_demo_data
    from app.db.models.shipment import ShipmentRecord
    from app.infrastructure.tenant_scope import tenant_scope

    state = compiled_chat_runtime
    actor, repository = state.actor, state.repository
    with tenant_scope(actor.tenant_id):
        seeded = seed_onboarding_demo_data(tenant_id=actor.tenant_id, industry_id="通用")
    customer, product = seeded["customer"]["name"], seeded["product"]["name"]
    plan = {
        "mode": "workflow",
        "intent": "onboarding_first_order",
        "todo_steps": ["查询客户", "查询产品", "确认后创建出货单"],
        "risk_level": "medium",
        "nodes": [
            {
                "node_id": "customer",
                "tool_id": "customers",
                "action": "query",
                "risk": "low",
                "idempotent": True,
                "params": {"keyword": customer},
            },
            {
                "node_id": "product",
                "tool_id": "products",
                "action": "query",
                "risk": "low",
                "idempotent": True,
                "params": {"keyword": product},
                "depends_on": ["customer"],
            },
            {
                "node_id": "shipment",
                "tool_id": "shipment_records",
                "action": "create",
                "risk": "medium",
                "idempotent": True,
                "depends_on": ["product"],
                "params": {
                    "unit_name": customer,
                    "products": [
                        {
                            "product_name": product,
                            "quantity_tins": 1,
                            "tin_spec": 1,
                            "unit_price": 99,
                            "amount": 99,
                        }
                    ],
                },
            },
        ],
    }
    prompt = f"查询客户{customer}和商品{product}，创建数量为1的演示出货单；涉及写入先让我确认。"

    def respond(**kwargs):
        request = json.loads(kwargs["messages"][-1]["content"])
        if request.get("task") == "audit_goal_coverage":
            return goal_review_response(
                request,
                source=prompt,
                node_ids=["customer", "product", "shipment"],
                outcome="execute",
            )
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    completion = Mock(side_effect=respond)
    state.completion = completion
    conversation = Mock(get_context=Mock(return_value=None))
    with patch(
        "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=conversation
    ):
        chat = AIChatApplicationService()
    for method in ("_persist_chat_turn", "_persist_recallable_chat_turn", "_persist_plan_state"):
        monkeypatch.setattr(chat, method, Mock())
    context = {**actor.context, "tool_execution_profile": profile, "memory_capture_enabled": False}
    with tenant_scope(actor.tenant_id):
        waiting_payload = chat.process_chat(
            str(actor.user_id), prompt, source=source, context=context
        )
        assert waiting_payload["data"]["action"] == "approval_pending", waiting_payload
        assert waiting_payload["execution_state"] == "waiting_user"
        parent_id = waiting_payload["run_id"]
        run_id = waiting_payload["data"]["data"]["approval_card"]["run_id"]
        assert run_id != parent_id
        assert len(repository.list_recent(limit=10)) == 2
        parent = repository.get(parent_id)
        frozen = parent.metadata["runtime_frozen_plan"]
        assert parent.status == "waiting_user"
        assert len(state.transports) == 1
        with actor.factory() as db:
            assert db.query(ShipmentRecord).count() == 0
        context.update(waiting_payload["runtime_context_update"])
        confirmed_payload = chat.process_chat(
            str(actor.user_id), "确认", source=source, context=context
        )
        assert confirmed_payload["data"]["action"] == "approval_pending", confirmed_payload
        assert confirmed_payload["run_id"] == parent_id
        assert confirmed_payload["data"]["data"]["approval_card"]["run_id"] == run_id
        waiting = repository.get(run_id)
        assert waiting.status == "waiting_user"
        assert waiting.metadata["runtime_context"]["_conversation_revision"] == 0
        assert [call.status for call in waiting.tool_calls] == ["completed", "completed"]
        assert waiting.steps[-1].params["products"][0]["tin_spec"] == 1
        with actor.factory() as db:
            assert db.query(ShipmentRecord).count() == 0
        approval = state.client.get(f"/api/agent/runs/{run_id}")
        assert approval.status_code == 200, approval.text
        grant = approval.json()["approval"]["grant"]
        approved = state.client.post(
            f"/api/agent/runs/{run_id}/continue", json={"approval_grant": grant}
        )
        assert approved.status_code == 202, approved.text
        with actor.factory() as db:
            assert db.query(ShipmentRecord).count() == 0
        completed = state.drain(run_id)
        assert completed.status == "completed", completed.error
        assert len(completed.tool_calls) == 3
        assert completion.call_count == 2
        assert json.loads(completion.call_args.kwargs["messages"][-1]["content"])["task"] == (
            "audit_goal_coverage"
        )
        conversation.chat.assert_not_called()
        assert state.client.get(f"/api/agent/runs/{parent_id}").status_code == 200
        parent = repository.get(parent_id)
        assert parent.status == "completed"
        assert parent.final_output["codex_result"]["business_completed"] is True
        assert parent.metadata["runtime_frozen_plan"] == frozen
        assert len(state.transports) == 1 and not chat._pending_workflows
        with actor.factory() as db:
            shipment = (
                db.query(ShipmentRecord).filter(ShipmentRecord.purchase_unit == customer).one()
            )
            assert shipment.product_name == product
            assert shipment.quantity_tins == shipment.tin_spec == 1
            assert shipment.unit_price == shipment.amount == 99
            assert shipment.tenant_id == actor.tenant_id


@pytest.mark.parametrize("industry", ["考勤", "考勤排班", "attendance", "attendance-industry"])
def test_attendance_onboarding_never_reads_or_writes_erp_or_private_roster(monkeypatch, industry):
    from app.application import onboarding_seed_app_service as service

    database = Mock(side_effect=AssertionError("attendance onboarding must not open a database"))
    customer = Mock(side_effect=AssertionError("must not manufacture an ERP department"))
    product = Mock(side_effect=AssertionError("must not manufacture an ERP employee"))
    monkeypatch.setattr(service, "get_db", database)
    monkeypatch.setattr(service, "build_customer_row", customer)
    monkeypatch.setattr(service, "build_product_row", product)
    for _ in range(2):
        result = service.seed_onboarding_demo_data(tenant_id=77, industry_id=industry)
        assert result["seeded"] is False
        assert result["seed_status"] == "workspace_review_required"
        assert result["customer"] is result["product"] is None
        assert result["workspace_path"] == "/attendance-industry/personnel"
        assert not result["demo_queries"]
    database.assert_not_called()
    customer.assert_not_called()
    product.assert_not_called()


def test_confirmation_action_string_without_real_wait_state_does_not_claim_execution(monkeypatch):
    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", repository
    )
    result = attach_chat_trace_run(
        {
            "success": True,
            "response": "已创建销售订单",
            "data": {"action": "workflow_confirmation_required"},
        },
        message="创建销售订单",
        user_id="spoof-test",
    )
    assert result["success"] is False
    assert result["data"]["action"] == "business_action_not_executed"
    assert repository.get(result["run_id"]).status == "failed"
