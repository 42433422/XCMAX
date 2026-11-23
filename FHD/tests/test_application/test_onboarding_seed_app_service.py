from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.codex_http_runtime import fixture_goal_review
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry


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
    monkeypatch, dynamic_chat_runtime, source, profile
) -> None:
    """Real host review, authenticated MCP child, approval and durable shipment."""
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.onboarding_seed_app_service import seed_onboarding_demo_data
    from app.db.models.shipment import ShipmentRecord
    from app.infrastructure.tenant_scope import tenant_scope

    state = dynamic_chat_runtime
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

    state.actions = [
        {
            "tool_id": node["tool_id"],
            "action": node["action"],
            "params": node["params"],
            "call_id": node["node_id"],
        }
        for node in plan["nodes"]
    ]
    state.review = lambda prompt: fixture_goal_review(prompt, kind="write")
    state.reply = "已核对客户和产品，并按原审批创建演示出货单。"
    chat = AIChatApplicationService()
    for method in ("_persist_chat_turn", "_persist_recallable_chat_turn"):
        monkeypatch.setattr(chat, method, Mock())
    context = {**actor.context, "tool_execution_profile": profile, "memory_capture_enabled": False}
    with tenant_scope(actor.tenant_id):
        waiting_payload = chat.process_chat(
            str(actor.user_id), prompt, source=source, context=context
        )
        assert waiting_payload["data"]["action"] == "approval_pending", str(
            {"payload": waiting_payload, "receipts": state.receipts}
        )
        assert waiting_payload["execution_state"] == "waiting_user"
        parent_id = waiting_payload["run_id"]
        run_id = waiting_payload["data"]["data"]["approval_card"]["run_id"]
        assert run_id != parent_id
        assert len(repository.list_recent(limit=10)) == 4
        parent = repository.get(parent_id)
        contract = parent.metadata["runtime_goal_contract"]
        assert contract["request"]["text"] == prompt
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
        assert not waiting.tool_calls, "the exact write child remains unexecuted before approval"
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
        assert completed.status == "completed", str(
            [(call.output, call.metadata.get("verification")) for call in completed.tool_calls]
        )
        assert len(completed.tool_calls) == 1
        assert state.client.get(f"/api/agent/runs/{parent_id}").status_code == 200
        parent = repository.get(parent_id)
        assert parent.status != "completed", (
            "status reads cannot run a model or mint goal completion"
        )
        assert state.model_requests == []
        parent = state.drain(parent_id)
        assert parent.status == "completed", parent.final_output
        assert parent.final_output["codex_result"]["business_completed"] is True
        assert parent.metadata["runtime_goal_contract"] == contract
        assert len(state.model_requests) == 1
        assert len(state.transports) == 2
        assert not hasattr(chat, "_pending_workflows")
        with actor.factory() as db:
            shipment = (
                db.query(ShipmentRecord).filter(ShipmentRecord.purchase_unit == customer).one()
            )
            assert shipment.product_name == product
            assert shipment.quantity_tins == shipment.tin_spec == 1
            assert shipment.unit_price == shipment.amount == 99
            assert shipment.tenant_id == actor.tenant_id


@pytest.fixture
def verified_shipment(trusted_actor, monkeypatch, tmp_path):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.shipment_app_service import ShipmentApplicationService
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor = trusted_actor(role="admin")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "shipment-claims.sqlite"))
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    orchestrator = AgentOrchestrator(
        repository=InMemoryAgentRunRepository(),
        tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="Create the original two-item shipment",
        runtime_context=actor.context,
        plan=PlanGraph(
            plan_id="shipment-proof",
            intent="shipment_create",
            nodes=[
                WorkflowNode(
                    node_id="shipment",
                    tool_id="shipment_records",
                    action="create",
                    params={
                        "unit_name": "Current tenant customer",
                        "products": [
                            {
                                "product_name": "Item A",
                                "quantity_tins": 2,
                                "tin_spec": 2,
                                "unit_price": 3,
                                "amount": 12,
                            },
                            {
                                "product_name": "Item B",
                                "quantity_tins": 1,
                                "tin_spec": 5,
                                "unit_price": 4,
                                "amount": 20,
                            },
                        ],
                    },
                )
            ],
        ),
    )
    assert run.status == "waiting_user" and not run.tool_calls
    run = orchestrator.continue_run(run.run_id, approved_by=str(actor.user_id))
    assert run.status == "completed", run.error
    monkeypatch.setattr(
        ShipmentApplicationService,
        "create_shipment",
        lambda *_args, **_kwargs: pytest.fail("Readback must not create another shipment"),
    )
    return actor, run


@pytest.mark.parametrize(
    "change", [None, "receipt", "tenant", "quantity", "second_item", "permission"]
)
def test_shipment_readback_checks_every_persisted_item_without_writes(verified_shipment, change):
    import copy
    import sqlite3

    from sqlalchemy import event

    from app.application.agent_orchestrator.result_verification import verify_step_result
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.agent_orchestrator.tool_permission import _idempotency_path
    from app.db.models.permission import Role
    from app.db.models.shipment import ShipmentRecord
    from app.infrastructure.tenant_scope import tenant_scope

    actor, run = verified_shipment
    step, call = run.steps[0], run.tool_calls[0]
    original = copy.deepcopy(call.output)
    if change == "receipt":
        with sqlite3.connect(_idempotency_path(create_parent=False)) as db:
            db.execute("DELETE FROM tool_idempotency")
    elif change is not None:
        with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
            row = db.get(ShipmentRecord, original["shipment"]["id"])
            if change == "tenant":
                row.tenant_id = actor.tenant_id + 1
            elif change == "quantity":
                row.quantity_kg = 42
            elif change == "second_item":
                parsed = json.loads(row.parsed_data)
                parsed["items"][1]["amount"] = 1
                row.parsed_data = json.dumps(parsed)
            elif change == "permission":
                role = db.query(Role).filter_by(name="admin").one()
                role.permissions = [
                    permission
                    for permission in role.permissions
                    if permission.code != "shipment.view"
                ]
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = actor.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            report = verify_step_result(
                run=run,
                step=step,
                call=call,
                context={
                    **run.metadata["runtime_context"],
                    "run_id": run.run_id,
                    "step_id": step.step_id,
                    **task_execution_context(run, step),
                },
            )
            assert report["accepted"] is (change is None), report
            assert report["code"] != "verification_binding_invalid"
            if change is None:
                assert report["checks"][0]["evidence"]["item_count"] == 2
        assert writes == []
        assert call.output == original and len(run.tool_calls) == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_shipment_claimed_success_cannot_borrow_an_existing_aggregate(verified_shipment):
    import copy

    from tests.test_application.test_verification_readback import invocation, verify

    actor, original = verified_shipment
    case = invocation(
        actor,
        tool="shipment_records",
        action="create",
        params=copy.deepcopy(original.steps[0].params),
    )
    report = verify(case, {**copy.deepcopy(original.tool_calls[0].output), "verified": True})
    assert report["status"] != "verified"
    assert report["code"] == "result_receipt_unavailable"


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
