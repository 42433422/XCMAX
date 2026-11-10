"""Sales approval with a synthetic plan and a real isolated business database."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook
from sqlalchemy import text

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.payment_service import payment
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models import Customer, InventoryLedger, JournalEntry, Product, Warehouse
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_approved_sales_plan_writes_once_and_does_not_invent_receipt(trusted_actor, monkeypatch):
    actor = trusted_actor(role="admin")
    factory = actor.factory
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
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
            "requested": False,
            "amount": 1000,
            "currency": "CNY",
            "receipt_voucher": None,
        },
    }
    plan = PlanGraph(
        plan_id="sales-agent-acceptance",
        intent="sales_write",
        nodes=[
            WorkflowNode(
                node_id="sale",
                tool_id="sales",
                action="execute_closed_loop",
                params={"payload": payload},
                risk="high",
                idempotent=True,
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
            repository=InMemoryAgentRunRepository(), tool_executor=executor
        )
        rejected_plan = deepcopy(plan)
        rejected_plan.plan_id = "sales-agent-rejected"
        rejected = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id),
            message="取消该销售",
            plan=rejected_plan,
            runtime_context=actor.context,
        )
        assert rejected.status == "waiting_user"
        stopped = orchestrator.cancel_run(rejected.run_id, requested_by=str(actor.user_id))
        assert stopped is not None and stopped.status == "cancelled"
        waiting = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id),
            message="销售并开票，不得虚构收款",
            plan=plan,
            runtime_context=actor.context,
        )
        assert waiting.status == "waiting_user" and not waiting.tool_calls
        with factory() as db:
            assert db.execute(text("SELECT count(*) FROM sales_orders")).scalar_one() == 0
        completed = orchestrator.continue_run(
            waiting.run_id, approved_by=str(actor.user_id), approved_step_id="sale"
        )
        assert completed is not None and completed.status == "completed", completed
        assert [step.status for step in completed.steps] == ["completed"] * 3
        from app.application.agent_orchestrator.artifact_files import read_verified_spreadsheet

        artifact = completed.steps[2].output["artifacts"][0]
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
        assert Decimal(str(orders[0][2] or 0)) == 0
        assert db.execute(text("SELECT count(*) FROM receivable_allocations")).scalar_one() == 0
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
        assert len(entries) == 1 and entries[0].is_balanced()
    with tenant_scope(actor.tenant_id):
        args = {
            "sales_order_id": orders[0][3],
            "amount": Decimal("1000"),
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
        assert db.execute(text("SELECT count(*) FROM receivable_allocations")).scalar_one() == 1
        assert (
            Decimal(str(db.execute(text("SELECT paid_amount FROM sales_orders")).scalar_one()))
            == 1000
        )
