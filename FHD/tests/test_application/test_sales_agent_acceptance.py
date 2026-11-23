"""Sales approval with a synthetic plan and a real isolated business database."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook
from sqlalchemy import text

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    issue_approval_grant,
    validate_approval_grant,
)
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.payment_service import payment, refund
from app.application.sales_app_service import SalesAppService
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models import Customer, InventoryLedger, JournalEntry, Product, Warehouse
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _seed_closed_loop_sale(trusted_actor, monkeypatch, tmp_path, approved_receipt):
    from app.db.models.permission import DEFAULT_ROLES

    permissions = next(row["permissions"] for row in DEFAULT_ROLES if row["name"] == "admin")
    actor = trusted_actor(role="admin", permissions=[*permissions, "tool.finance.ledger_query"])
    monkeypatch.setattr(
        "app.infrastructure.auth.business_scope_gate.resolve_product_sku", lambda: "enterprise"
    )
    factory = actor.factory
    monkeypatch.setattr("app.db.SessionLocal", factory)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "sales-tool-claims.sqlite"))
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", factory)
    now = datetime.now()
    with tenant_scope(actor.tenant_id), factory.begin() as db:
        customer = Customer(customer_name="测试客户 A")
        product = Product(name="产品 B", unit="件", model_number="TEST-B", is_active=1)
        warehouse = Warehouse(
            code="WH-A", name="验收仓", status="active", created_at=now, updated_at=now
        )
        db.add_all([customer, product, warehouse])
        db.flush()
        db.add(
            InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=20,
                available_quantity=20,
                reserved_quantity=0,
                unit="件",
                in_date=now.date(),
                created_at=now,
                updated_at=now,
            )
        )
    other_tenant = actor.tenant_id + 1
    with tenant_scope(other_tenant), factory.begin() as db:
        other_product = Product(name="产品 B", unit="件", model_number="OTHER-B", is_active=1)
        other_warehouse = Warehouse(
            code="WH-B", name="其他企业仓", status="active", created_at=now, updated_at=now
        )
        db.add_all([Customer(customer_name="测试客户 A"), other_product, other_warehouse])
        db.flush()
        db.add(
            InventoryLedger(
                product_id=other_product.id,
                warehouse_id=other_warehouse.id,
                quantity=20,
                available_quantity=20,
                reserved_quantity=0,
                unit="件",
                in_date=now.date(),
                created_at=now,
                updated_at=now,
            )
        )
    payload = {
        "acceptance_profile": "sales-order-v1",
        "idempotency_key": "sales-agent-acceptance",
        "order": {
            "customer_name": "测试客户 A",
            "customer_resolution": "current_tenant_exact_name",
            "currency": "CNY",
            "items": [
                {
                    "product_name": "产品 B",
                    "product_resolution": "current_tenant_exact_name",
                    "quantity": 10,
                    "unit": "件",
                    "unit_price": 100,
                    "line_total": 1000,
                }
            ],
            "total_amount": 1000,
        },
        "fulfillment": {
            "requested": True,
            "quantity": 10,
            "unit": "件",
            "warehouse_resolution": "current_tenant_default",
        },
        "invoice": {"requested": True, "amount": 1000, "currency": "CNY"},
        "payment_allocation": {
            "requested": bool(approved_receipt),
            "amount": approved_receipt or 1000,
            "currency": "CNY",
            "receipt_voucher": None,
        },
    }
    return actor, payload, other_tenant


@pytest.mark.parametrize("approved_receipt", [0, 375])
def test_approved_sales_plan_writes_once_and_does_not_invent_receipt(
    trusted_actor, monkeypatch, tmp_path, approved_receipt
):
    actor, payload, other_tenant = _seed_closed_loop_sale(
        trusted_actor, monkeypatch, tmp_path, approved_receipt
    )
    factory = actor.factory
    plan = PlanGraph(
        plan_id="sales-agent-acceptance",
        intent="sales_write",
        nodes=[
            WorkflowNode(
                node_id="lookup",
                tool_id="customers",
                action="query",
                params={"keyword": "测试客户 A"},
                risk="low",
                idempotent=True,
            ),
            WorkflowNode(
                node_id="sale",
                tool_id="sales",
                action="execute_closed_loop",
                params={"payload": payload},
                risk="high",
                idempotent=True,
                depends_on=["lookup"],
            ),
            WorkflowNode(
                node_id="verify",
                tool_id="sales",
                action="verify_closed_loop",
                params={"payload": payload},
                risk="low",
                idempotent=True,
                depends_on=["sale"],
            ),
            WorkflowNode(
                node_id="export",
                tool_id="reports",
                action="export",
                params={"report_type": "sales", "group_by": "product", "filename": "销售订单验收"},
                risk="low",
                idempotent=True,
                depends_on=["verify"],
            ),
        ],
    )
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    with tenant_scope(actor.tenant_id):
        orchestrator = AgentOrchestrator(
            repository=SQLAlchemyAgentRunRepository(session_factory=factory), tool_executor=executor
        )
        rejected_plan = deepcopy(plan)
        rejected_plan.plan_id = "sales-agent-rejected"
        rejected = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id),
            message="取消该销售",
            plan=rejected_plan,
            runtime_context=actor.context,
        )
        assert rejected.status == "waiting_user", (
            rejected.error,
            [s.output for s in rejected.steps],
        )
        stopped = orchestrator.cancel_run(rejected.run_id, requested_by=str(actor.user_id))
        assert stopped is not None and stopped.status == "cancelled"
        waiting = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id),
            message=(
                f"销售并开票，已收到 {approved_receipt} 元"
                if approved_receipt
                else "销售并开票，不得虚构收款"
            ),
            plan=plan,
            runtime_context=actor.context,
        )
        assert waiting.status == "waiting_user"
        assert [step.status for step in waiting.steps] == [
            "completed",
            "waiting_user",
            "pending",
            "pending",
        ]
        assert len(waiting.tool_calls) == 1
        with factory() as db:
            assert db.execute(text("SELECT count(*) FROM sales_orders")).scalar_one() == 0
        if approved_receipt:
            grant = issue_approval_grant(waiting, principal_id=str(actor.user_id))
            assert grant is not None
        # Recreate the orchestrator and repository to prove the pending plan survives a restart.
        orchestrator = AgentOrchestrator(
            repository=SQLAlchemyAgentRunRepository(session_factory=factory), tool_executor=executor
        )
        reloaded = orchestrator.get_run(waiting.run_id)
        assert reloaded is not None and reloaded.status == "waiting_user"
        if approved_receipt:
            claims = validate_approval_grant(
                grant["grant"], run=reloaded, principal_id=str(actor.user_id)
            )
            assert claims["params_sha256"]
            changed = deepcopy(reloaded)
            changed.steps[1].params["payload"]["payment_allocation"]["amount"] = (
                approved_receipt + 1
            )
            with pytest.raises(ApprovalGrantError, match="不匹配"):
                validate_approval_grant(
                    grant["grant"], run=changed, principal_id=str(actor.user_id)
                )
        completed = orchestrator.continue_run(
            waiting.run_id, approved_by=str(actor.user_id), approved_step_id="sale"
        )
        assert completed is not None and completed.status == "completed", completed
        assert [step.status for step in completed.steps] == ["completed"] * 4
        if approved_receipt:
            assert completed.steps[2].output["remaining_receivable"] == "625.00"
            assert completed.steps[2].output["payment_state"] == "partial"
            assert completed.metadata["plan_sha256"] == reloaded.metadata["plan_sha256"]
            approved_payload = completed.steps[1].params["payload"]
            replay = SalesAppService().execute_closed_loop(approved_payload)
            assert replay["success"] and replay["replayed"], replay
            conflict = SalesAppService().execute_closed_loop(changed.steps[1].params["payload"])
            assert conflict["failed_step"] == "idempotency", conflict
        assert sum(call.node_id == "lookup" for call in completed.tool_calls) == 1
        from app.application.agent_orchestrator.artifact_files import read_verified_spreadsheet

        artifact = completed.steps[3].output["artifacts"][0]
        workbook = load_workbook(BytesIO(read_verified_spreadsheet(completed.run_id, artifact)))
        rows = list(workbook["sales"].iter_rows(values_only=True))
        assert "产品 B" in str(rows) and "1000" in str(rows)
        orchestrator.continue_run(
            waiting.run_id, approved_by=str(actor.user_id), approved_step_id="sale"
        )
    with factory() as db:
        orders = db.execute(
            text("SELECT tenant_id, total_amount, paid_amount, id FROM sales_orders")
        ).all()
        assert len(orders) == 1 and orders[0][0] == actor.tenant_id
        assert Decimal(str(orders[0][1])) == Decimal("1000")
        assert Decimal(str(orders[0][2] or 0)) == approved_receipt
        assert db.execute(text("SELECT count(*) FROM receivable_allocations")).scalar_one() == bool(
            approved_receipt
        )
        assert (
            db.execute(text("SELECT invoice_status FROM sales_orders")).scalar_one() == "invoiced"
        )
        assert (
            Decimal(
                str(
                    db.execute(
                        text(
                            "SELECT available_quantity FROM inventory_ledger WHERE tenant_id = :tenant"
                        ),
                        {"tenant": actor.tenant_id},
                    ).scalar_one()
                )
            )
            == 10
        )
        assert (
            Decimal(
                str(
                    db.execute(
                        text(
                            "SELECT available_quantity FROM inventory_ledger WHERE tenant_id = :tenant"
                        ),
                        {"tenant": other_tenant},
                    ).scalar_one()
                )
            )
            == 20
        )
        movements = db.execute(
            text("SELECT transaction_type, quantity FROM inventory_transactions")
        ).all()
        assert len(movements) == 1 and movements[0][0] == "out"
        assert Decimal(str(movements[0][1])) == -10
    with tenant_scope(actor.tenant_id), factory() as db:
        entries = db.query(JournalEntry).all()
        assert len(entries) == 1 + bool(approved_receipt)
        assert all(entry.is_balanced() for entry in entries)
    with tenant_scope(actor.tenant_id):
        args = {
            "sales_order_id": orders[0][3],
            "amount": Decimal(1000 - approved_receipt),
            "reference": "TEST-BANK-RECEIPT",
            "idempotency_key": "sales-agent-receipt",
        }
        assert payment(**args)["success"] is True
        assert payment(**args).get("idempotent") is True
        assert (
            payment(**{**args, "amount": Decimal("1"), "idempotency_key": "extra"})["success"]
            is False
        )
    with factory() as db:
        assert db.execute(
            text("SELECT count(*) FROM receivable_allocations")
        ).scalar_one() == 1 + bool(approved_receipt)
        assert (
            Decimal(str(db.execute(text("SELECT paid_amount FROM sales_orders")).scalar_one()))
            == 1000
        )

    if approved_receipt:
        with tenant_scope(actor.tenant_id):
            assert refund(allocation_id=replay["data"]["payment_allocation_id"])["success"]
            assert SalesAppService().execute_closed_loop(approved_payload)["failed_step"] == (
                "payment_reconciliation"
            )
        with factory() as db:
            assert db.execute(text("SELECT count(*) FROM receivable_allocations")).scalar_one() == 3
            assert db.execute(text("SELECT count(*) FROM journal_entries")).scalar_one() == 4
            assert (
                Decimal(str(db.execute(text("SELECT paid_amount FROM sales_orders")).scalar_one()))
                == 625
            )


@pytest.fixture
def verified_closed_loop(trusted_actor, monkeypatch, tmp_path):
    actor, payload, _ = _seed_closed_loop_sale(trusted_actor, monkeypatch, tmp_path, 375)
    orchestrator = AgentOrchestrator(
        repository=SQLAlchemyAgentRunRepository(session_factory=actor.factory),
        tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    run = orchestrator.start_run_from_plan(
        user_id=str(actor.user_id),
        message="Approve the original sale with its actual partial receipt",
        runtime_context=actor.context,
        plan=PlanGraph(
            plan_id="sales-independent-proof",
            intent="sales_write",
            nodes=[
                WorkflowNode(
                    node_id="sale",
                    tool_id="sales",
                    action="execute_closed_loop",
                    params={"payload": payload},
                    risk="high",
                    idempotent=True,
                )
            ],
        ),
    )
    assert run.status == "waiting_user" and not run.tool_calls
    run = orchestrator.continue_run(run.run_id, approved_by=str(actor.user_id))
    assert run.status == "completed", run.error
    monkeypatch.setattr(
        SalesAppService,
        "execute_closed_loop",
        lambda *_args, **_kwargs: pytest.fail("Verification must not replay the sale"),
    )
    return actor, run


@pytest.mark.parametrize(
    "change",
    [
        None,
        "receipt",
        "fingerprint",
        "tenant",
        "stock",
        "amount",
        "payment",
        "customer",
        "permission",
    ],
)
def test_closed_loop_verification_reads_original_receipt_and_current_ledger_without_writes(
    verified_closed_loop, monkeypatch, change
):
    import sqlite3

    from sqlalchemy import event

    from app.application.agent_orchestrator.result_verification import verify_step_result
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.agent_orchestrator.tool_permission import _idempotency_path
    from app.db.models import InventoryTransaction, ReceivableAllocation, SalesOrder
    from app.db.models.permission import Role

    actor, run = verified_closed_loop
    step, call = run.steps[0], run.tool_calls[0]
    original = deepcopy(call.output)
    if change == "receipt":
        with sqlite3.connect(_idempotency_path(create_parent=False)) as db:
            db.execute("DELETE FROM tool_idempotency")
    elif change is not None:
        with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
            order = db.get(SalesOrder, original["data"]["order_id"])
            if change == "fingerprint":
                order.remark = "changed transaction identity"
            elif change == "tenant":
                order.tenant_id = actor.tenant_id + 1
            elif change == "stock":
                db.query(InventoryTransaction).filter_by(
                    sales_order_id=order.id
                ).one().quantity = -9
            elif change == "amount":
                order.total_amount = 1001
            elif change == "payment":
                db.get(
                    ReceivableAllocation, original["data"]["payment_allocation_id"]
                ).status = "refunded"
            elif change == "customer":
                db.get(Customer, order.customer_id).customer_name = "Changed customer"
            elif change == "permission":
                role = db.query(Role).filter_by(name="admin").one()
                role.permissions = [
                    p for p in role.permissions if p.code != "tool.finance.ledger_query"
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
                evidence = report["checks"][0]["evidence"]
                assert evidence["scope"] == "current_sales_closed_loop_state"
                assert evidence["attribution"] == "not_inferred"
        assert writes == []
        assert call.output == original and len(run.tool_calls) == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def test_forged_closed_loop_success_cannot_borrow_an_existing_sale(verified_closed_loop):
    from app.application.agent_orchestrator.result_verification import freeze_verification_contract
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from tests.test_application.test_sales_verification_readback import verify
    from tests.test_application.test_verification_readback import invocation

    actor, original = verified_closed_loop
    case = invocation(
        actor,
        tool="sales",
        action="execute_closed_loop",
        params=deepcopy(original.steps[0].params),
    )
    freeze_verification_contract(
        case.run,
        case.step,
        case.call,
        get_tool_action_spec("sales", "execute_closed_loop"),
        case.context,
    )
    output = {**deepcopy(original.tool_calls[0].output), "verified": True}
    report = verify(case, output)
    assert report["accepted"] is False
    assert report["code"] == "result_receipt_unavailable"
