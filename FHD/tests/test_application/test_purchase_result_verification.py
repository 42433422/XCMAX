"""Original procurement requests, bounded receiving and independent SQL readback."""

from __future__ import annotations

import copy
from datetime import date

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def procurement(trusted_actor, monkeypatch):
    from app import db as host_db
    from app.db.models import Product, PurchaseOrder, PurchaseOrderItem, Supplier, Warehouse
    from app.domain.shared_services.purchase_service import PurchaseService
    from app.infrastructure.tenant_scope import owned_tenant_scope

    actor = trusted_actor(
        permissions=[
            "tool.purchase.create_order",
            "tool.purchase.approve_order",
            "tool.purchase.update_order",
            "tool.purchase.cancel_order",
            "tool.purchase.create_inbound",
            "tool.purchase.query_orders",
            "tool.purchase.query_inbounds",
            "tool.finance.ledger_query",
            "tool.inventory.query",
        ]
    )
    monkeypatch.setattr(host_db, "SessionLocal", actor.factory)
    monkeypatch.setattr(PurchaseService, "_publish_event", lambda *args, **kwargs: None)
    with owned_tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        db.add(Supplier(id=1, code="supplier-1", name="供应商", status="active"))
        db.add(Product(id=1, name="资源物料"))
        db.add(Warehouse(id=1, code="warehouse-1", name="仓库"))
        db.flush()
        db.add(
            PurchaseOrder(
                id=1,
                order_no="original-purchase",
                supplier_id=1,
                warehouse_id=1,
                order_date=date.today(),
                status="draft",
                total_amount=100,
            )
        )
        db.flush()
        db.add(
            PurchaseOrderItem(
                id=1,
                order_id=1,
                product_id=1,
                quantity=10,
                unit_price=10,
                amount=100,
                received_quantity=0,
                status="pending",
            )
        )
    return actor


def _receive(actor, **changes):
    from app.domain.shared_services.purchase_service import PurchaseService
    from app.infrastructure.tenant_scope import owned_tenant_scope

    request = {
        "order_id": 1,
        "supplier_id": 1,
        "warehouse_id": 1,
        "items": [{"order_item_id": 1, "product_id": 1, "quantity": 2, "unit_price": 10}],
    }
    with owned_tenant_scope(actor.tenant_id):
        return PurchaseService().create_purchase_inbound({**request, **changes})


def _approve(actor):
    from app.domain.shared_services.purchase_service import PurchaseService
    from app.infrastructure.tenant_scope import owned_tenant_scope

    with owned_tenant_scope(actor.tenant_id):
        return PurchaseService().approve_purchase_order(1, str(actor.user_id))


def test_inbound_cannot_consume_unapproved_order(procurement):
    assert _receive(procurement)["success"] is False


def test_inbound_cannot_exceed_approved_amount_or_quantity(procurement):
    assert _approve(procurement)["success"]
    result = _receive(
        procurement, items=[{"order_item_id": 1, "product_id": 1, "quantity": 11, "unit_price": 10}]
    )
    assert result["success"] is False


def test_accounting_failure_rolls_back_stock_and_inbound(procurement, monkeypatch):
    from app.db.models import InventoryTransaction, PurchaseInbound, PurchaseOrderItem
    from app.infrastructure.tenant_scope import owned_tenant_scope

    assert _approve(procurement)["success"]
    monkeypatch.setattr(
        "app.domain.shared_services.accounting_services.create_journal_entry",
        lambda *args, **kwargs: {"success": False, "message": "ledger unavailable"},
    )
    assert _receive(procurement)["success"] is False
    with owned_tenant_scope(procurement.tenant_id), procurement.factory() as db:
        assert db.query(InventoryTransaction).count() == 0
        assert db.query(PurchaseInbound).count() == 0
        assert db.get(PurchaseOrderItem, 1).received_quantity == 0


def test_edit_cannot_bypass_original_purchase_approval(procurement):
    from app.domain.shared_services.purchase_service import PurchaseService
    from app.infrastructure.tenant_scope import owned_tenant_scope

    with owned_tenant_scope(procurement.tenant_id):
        output = PurchaseService().update_purchase_order(1, {"status": "approved"})
    assert output["success"] is False
    assert _receive(procurement)["success"] is False


def prepare(actor, action, **changes):
    from app.application.agent_orchestrator.result_verification import freeze_verification_contract
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from tests.test_application.test_verification_readback import invocation

    params = {"order_id": 1}
    if action in {"create_order", "create_inbound"}:
        params.update(
            supplier_id=1,
            warehouse_id=1,
            items=[{"product_id": 1, "quantity": 2, "unit_price": 10}],
        )
        if action == "create_order":
            params.pop("order_id")
        else:
            params["items"][0]["order_item_id"] = 1
    if action == "update_order":
        params["remark"] = "confirmed requirement"
    case = invocation(actor, tool="purchase", action=action, params={**params, **changes})
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("purchase", action), case.context
    )
    assert case.call.metadata["verification_contract"]["authority_baseline"]["status"] == "observed"
    return case


def effect(actor, case):
    from app.domain.shared_services.tools_workflow_erp import _registered_router_purchase
    from app.infrastructure.tenant_scope import owned_tenant_scope

    with owned_tenant_scope(actor.tenant_id):
        return _registered_router_purchase(
            case.step.action, case.step.params, case.context, "", "isolated local procurement test"
        )


def verify(case, output):
    from app.application.agent_orchestrator.result_verification import (
        bind_execution_receipt,
        verify_step_result,
    )

    case.step.status = case.call.status = "completed"
    case.step.output, case.call.output = copy.deepcopy(output), copy.deepcopy(output)
    bind_execution_receipt(case.call)
    return verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)


@pytest.mark.parametrize(
    "action", ["create_order", "update_order", "approve_order", "cancel_order", "create_inbound"]
)
def test_original_purchase_writes_have_independent_readback(procurement, action):
    from sqlalchemy import event

    if action == "create_inbound":
        assert _approve(procurement)["success"]
    case = prepare(procurement, action)
    output = effect(procurement, case)
    assert output["success"], output
    writes = []

    def observe(_connection, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = procurement.factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(2):
            result = verify(case, output)
            assert result["accepted"] is True, result
            assert result["status"] == "verified"
            assert result["checks"][0]["evidence"]["external_purchase_verified"] is False
        assert writes == []
    finally:
        event.remove(engine, "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "action", ["create_order", "update_order", "approve_order", "cancel_order", "create_inbound"]
)
def test_claims_and_old_documents_are_not_purchase_execution(procurement, action):
    if action == "create_inbound":
        assert _approve(procurement)["success"]
    case = prepare(procurement, action)
    assert not verify(case, {"success": True, "verified": True, "data": {"id": 1}})["accepted"]
    output = effect(procurement, case)
    assert output["success"], output
    assert verify(case, output)["accepted"]
    if action in {"create_order", "create_inbound"}:
        unrelated = prepare(procurement, action)
        assert not verify(unrelated, output)["accepted"]
        replay = effect(procurement, case)
        assert not replay["success"]  # Native unique document number forbids another effect.


def test_supplier_limit_and_duplicate_lines_bound_real_receiving(procurement):
    from app.db.models import Supplier
    from app.infrastructure.tenant_scope import owned_tenant_scope

    with owned_tenant_scope(procurement.tenant_id), procurement.factory.begin() as db:
        db.get(Supplier, 1).credit_limit = 99
    assert not _approve(procurement)["success"]
    with owned_tenant_scope(procurement.tenant_id), procurement.factory.begin() as db:
        db.get(Supplier, 1).credit_limit = 100
    assert _approve(procurement)["success"]
    line = {"order_item_id": 1, "product_id": 1, "quantity": 6, "unit_price": 10}
    assert not _receive(procurement, items=[line, line])["success"]
    assert _receive(procurement, items=[line])["success"]
    assert not _receive(procurement, items=[line])["success"]


def test_concurrent_approvals_cannot_both_spend_the_same_supplier_limit(procurement):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.db.models import PurchaseOrder, PurchaseOrderItem, Supplier
    from app.domain.shared_services.purchase_service import PurchaseService
    from app.infrastructure.tenant_scope import owned_tenant_scope

    with owned_tenant_scope(procurement.tenant_id), procurement.factory.begin() as db:
        db.get(Supplier, 1).credit_limit = 100
        db.add(
            PurchaseOrder(
                id=2,
                order_no="other-approved-requirement",
                supplier_id=1,
                warehouse_id=1,
                order_date=date.today(),
                status="draft",
                total_amount=100,
            )
        )
        db.flush()
        db.add(PurchaseOrderItem(order_id=2, product_id=1, quantity=10, unit_price=10, amount=100))
    start = Barrier(2)

    def approve(order_id):
        with owned_tenant_scope(procurement.tenant_id):
            start.wait(timeout=10)
            return PurchaseService().approve_purchase_order(order_id, str(procurement.user_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, [1, 2]))
    assert sum(row["success"] for row in outcomes) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"supplier_id": 2},
        {"warehouse_id": 2},
        {"items": [{"order_item_id": 1, "product_id": 1, "quantity": 2, "unit_price": 11}]},
        {"items": [{"order_item_id": 99, "product_id": 1, "quantity": 2, "unit_price": 10}]},
    ],
)
def test_receiving_rejects_scope_or_price_changes(procurement, change):
    assert _approve(procurement)["success"]
    assert not _receive(procurement, **change)["success"]


def test_readback_rejects_removed_journal_and_revoked_actor(procurement):
    from app.db.models import JournalEntry
    from app.db.models.permission import Role
    from app.infrastructure.tenant_scope import owned_tenant_scope

    assert _approve(procurement)["success"]
    case = prepare(procurement, "create_inbound")
    output = effect(procurement, case)
    assert verify(case, output)["accepted"]
    with owned_tenant_scope(procurement.tenant_id), procurement.factory.begin() as db:
        db.get(JournalEntry, output["data"]["journal_entry_id"]).status = "draft"
    assert not verify(case, output)["accepted"]
    with procurement.factory.begin() as db:
        for role in db.query(Role).all():
            role.permissions = []
    assert not verify(case, output)["accepted"]


@pytest.mark.parametrize("action", ["create_order", "create_inbound"])
def test_another_concurrent_execution_with_same_content_cannot_close_original(procurement, action):
    if action == "create_inbound":
        assert _approve(procurement)["success"]
    original = prepare(procurement, action)
    other = prepare(procurement, action)
    output = effect(procurement, other)
    assert verify(other, output)["accepted"]
    assert not verify(original, output)["accepted"]


def test_foreign_tenant_order_cannot_supply_purchase_baseline(procurement):
    from app.application.agent_orchestrator.result_verification import freeze_verification_contract
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.db.models import PurchaseOrder, Supplier
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from tests.test_application.test_verification_readback import invocation

    with owned_tenant_scope(procurement.tenant_id + 1), procurement.factory.begin() as db:
        supplier = Supplier(code="foreign-supplier", name="Foreign supplier", status="active")
        db.add(supplier)
        db.flush()
        row = PurchaseOrder(
            order_no="foreign-purchase",
            supplier_id=supplier.id,
            order_date=date.today(),
            status="draft",
            total_amount=100,
        )
        db.add(row)
        db.flush()
        order_id = row.id
    case = invocation(
        procurement, tool="purchase", action="approve_order", params={"order_id": order_id}
    )
    freeze_verification_contract(
        case.run,
        case.step,
        case.call,
        get_tool_action_spec("purchase", "approve_order"),
        case.context,
    )
    assert (
        case.call.metadata["verification_contract"]["authority_baseline"]["status"] == "unavailable"
    )
    assert not verify(case, {"success": True, "data": {"id": order_id}})["accepted"]


def test_original_approved_agent_task_receives_and_accounts_once(
    procurement, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models import InventoryTransaction, JournalEntry, PurchaseInbound
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from tests.test_application.test_enterprise_acceptance import _approve_and_execute

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    assert _approve(procurement)["success"]
    repository = SQLAlchemyAgentRunRepository(session_factory=procurement.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=procurement.factory)
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    orchestrator = AgentOrchestrator(repository=repository, tool_executor=executor)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda repo: AgentOrchestrator(
            repository=repo, tool_executor=executor
        ),
    )
    plan = PlanGraph(
        plan_id="receive-approved-resource",
        intent="receive_approved_resource",
        nodes=[
            WorkflowNode(
                "receive",
                "purchase",
                "create_inbound",
                {
                    "order_id": 1,
                    "supplier_id": 1,
                    "warehouse_id": 1,
                    "items": [
                        {"order_item_id": 1, "product_id": 1, "quantity": 2, "unit_price": 10}
                    ],
                },
                risk="high",
                idempotent=False,
            )
        ],
        metadata={"approval_required_node_ids": ["receive"]},
    )
    run = orchestrator.start_task_from_plan(
        user_id=str(procurement.user_id),
        message="登记原批准采购订单的实际到货",
        plan=plan,
        runtime_context=procurement.context,
    )
    assert run.status == "waiting_user" and not run.tool_calls
    completed, _ = _approve_and_execute(procurement, repository, queue, dispatcher, run)
    assert completed.status == "completed", completed.to_dict()
    assert completed.tool_calls[0].metadata["verification"]["status"] == "verified"
    assert queue.get(run.run_id).state == "succeeded"
    assert queue.claim("duplicate-worker", run_id=run.run_id, lease_seconds=30) is None
    with owned_tenant_scope(procurement.tenant_id), procurement.factory() as db:
        assert db.query(PurchaseInbound).count() == 1
        assert db.query(InventoryTransaction).count() == 1
        assert db.query(JournalEntry).filter_by(reference_type="purchase_inbound").count() == 1
