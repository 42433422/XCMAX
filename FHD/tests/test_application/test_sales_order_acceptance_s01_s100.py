"""销售订单全链路专项验收：生产路由、审批门控和隔离 SQLite，不伪造业务结果。"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.payment_service import payment, refund
from app.application.sales_app_service import SalesAppService
from app.application.sales_lifecycle_service import SalesLifecycleService
from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
from app.db.db_base import Base
from app.db.models import (
    Customer,
    InventoryLedger,
    InventoryTransaction,
    JournalEntry,
    Product,
    ReceivableAllocation,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.domain.shared_services.fulfillment_service import FulfillmentService
from app.domain.shared_services.tools_workflow_registered import execute_registered_workflow_tool
from app.infrastructure.tenant_scope import tenant_scope

SENTENCE = (
    "帮我给测试客户 A 销售 10 件产品 B，每件 100 元。先检查客户和库存，生成订单给我确认。"
    "批准后完成出库、发货和开票；收款必须依据实际到账凭证登记。最后核对订单、库存、发货、发票和收款，并导出结果。"
)
VOUCHER = "BANK-RECEIPT-S01-001"


def _plan(sentence: str):
    planner = object.__new__(LLMWorkflowPlanner)
    return planner._fallback_plan("wp-sales-acceptance", sentence, get_tool_registry())


def _engine(approval: ApprovalService) -> ApprovalGatedEngine:
    approval._persist_request_to_db = lambda *a, **k: None
    return ApprovalGatedEngine(
        engine=WorkflowEngine(tool_dispatcher=execute_registered_workflow_tool),
        approval_service=approval,
    )


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sales-acceptance.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    yield factory
    engine.dispose()


def _seed(factory) -> dict:
    created = {}
    for tenant_id, code, qty in ((1, "WH-A", 20), (2, "WH-B", 20)):
        with tenant_scope(tenant_id):
            db = factory()
            customer = Customer(customer_name="测试客户 A")
            product = Product(name="产品 B", unit="件", model_number="TEST-B-001", is_active=1)
            lookalike = Product(
                name="产品 B 加强", unit="件", model_number="TEST-B-002", is_active=1
            )
            inactive = Product(name="产品 C", unit="件", model_number="TEST-C-001", is_active=0)
            scarce = Product(name="产品 D", unit="件", model_number="TEST-D-001", is_active=1)
            warehouse = Warehouse(
                code=code,
                name=f"企业{tenant_id}仓",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([customer, product, lookalike, inactive, scarce, warehouse])
            db.flush()
            now = datetime.now()
            for row, amount in ((product, qty), (lookalike, 7), (scarce, 5)):
                db.add(
                    InventoryLedger(
                        product_id=row.id,
                        warehouse_id=warehouse.id,
                        quantity=amount,
                        available_quantity=amount,
                        reserved_quantity=0,
                        unit="件",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    )
                )
            db.commit()
            created[tenant_id] = {
                "customer_id": customer.id,
                "product_id": product.id,
                "lookalike_id": lookalike.id,
                "inactive_id": inactive.id,
                "scarce_id": scarce.id,
                "warehouse_id": warehouse.id,
            }
            db.close()
    return created


def _available(factory, tenant_id: int, product_id: int) -> Decimal:
    with tenant_scope(tenant_id):
        db = factory()
        try:
            ledger = (
                db.query(InventoryLedger).filter(InventoryLedger.product_id == product_id).one()
            )
            return Decimal(str(ledger.available_quantity))
        finally:
            db.close()


def _reserved(factory, tenant_id: int, product_id: int) -> Decimal:
    with tenant_scope(tenant_id):
        db = factory()
        try:
            ledger = (
                db.query(InventoryLedger).filter(InventoryLedger.product_id == product_id).one()
            )
            return Decimal(str(ledger.reserved_quantity or 0))
        finally:
            db.close()


def test_acceptance_sentence_is_a_gated_sales_plan():
    route = route_normal_mode_message(SENTENCE)
    assert route["intent"] == "sales_write"
    payload = route["payload"]
    item = payload["order"]["items"][0]
    assert payload["order"]["customer_name"] == "测试客户 A"
    assert item["product_name"] == "产品 B"
    assert item["quantity"] == 10
    assert item["unit"] == "件"
    assert item["unit_price"] == 100
    assert payload["order"]["total_amount"] == 1000
    assert payload["invoice"]["requested"] is True
    assert payload["payment_allocation"]["requested"] is False
    assert route_normal_mode_message("帮我给测试客户 A 销售")["intent"] != "sales_write"
    assert (
        route_normal_mode_message("帮我给测试客户 A 销售 0 件产品 B，每件 100 元")["intent"]
        != "sales_write"
    )
    plan = _plan(SENTENCE)
    assert [node.node_id for node in plan.nodes] == [
        "sales_execute_closed_loop",
        "verify_sales_result",
        "export_sales",
    ]
    assert plan.nodes[0].risk == "high"
    assert plan.nodes[1].depends_on == ["sales_execute_closed_loop"]
    assert plan.nodes[2].depends_on == ["verify_sales_result"]
    approval = ApprovalService()
    decision, run_result = _engine(approval).run(
        plan, {"message": SENTENCE}, strategy="interactive"
    )
    assert decision.pending_approval is True
    assert run_result is None
    assert approval.approve("missing", comment="no") is False


def test_sales_order_acceptance_isolated_database(isolated_db):
    factory = isolated_db
    seed = _seed(factory)
    product_id = seed[1]["product_id"]
    assert _available(factory, 1, product_id) == Decimal("20")
    assert _reserved(factory, 1, product_id) == Decimal("0")

    with tenant_scope(1):
        route = route_normal_mode_message(SENTENCE)
        plan = _plan(SENTENCE)
        approval = ApprovalService()
        gated = _engine(approval)
        decision, pending = gated.run(plan, {"message": SENTENCE}, strategy="interactive")
        assert decision.pending_approval is True and pending is None
        assert factory().query(SalesOrder).count() == 0
        request = approval.get_requests_by_plan(plan.plan_id)[0]
        assert approval.approve(request.request_id, comment="验收批准") is True
        assert approval.approve(request.request_id, comment="重复批准") is False
        result = gated.resume_after_approval(
            plan, {request.request_id: True}, {"message": SENTENCE}
        )
        assert result.success is True, result.message
        replay = gated.resume_after_approval(
            plan, {request.request_id: True}, {"message": SENTENCE}
        )
        assert replay.success is True

    with tenant_scope(1):
        db = factory()
        order = db.query(SalesOrder).one()
        item = db.query(SalesOrderItem).one()
        outs = (
            db.query(InventoryTransaction)
            .filter(InventoryTransaction.transaction_type == "out")
            .all()
        )
        entries = db.query(JournalEntry).all()
        db.close()
    assert order.customer_id == seed[1]["customer_id"]
    assert order.order_no
    assert item.product_id == product_id
    assert item.product_id != seed[1]["lookalike_id"]
    assert Decimal(str(item.quantity)) == Decimal("10")
    assert Decimal(str(item.unit_price)) == Decimal("100")
    assert Decimal(str(order.total_amount)) == Decimal("1000")
    assert Decimal(str(item.amount)) == Decimal("1000")
    assert order.payment_state == "unpaid"
    assert Decimal(str(order.paid_amount or 0)) == Decimal("0")
    assert order.invoice_status == "invoiced"
    assert len(outs) == 1
    assert outs[0].product_id == product_id
    assert outs[0].warehouse_id == seed[1]["warehouse_id"]
    assert outs[0].sales_order_id == order.id
    assert Decimal(str(outs[0].quantity)) == Decimal("-10")
    assert _available(factory, 1, product_id) == Decimal("10")
    assert len(entries) == 1 and entries[0].is_balanced()
    assert all(entry.reference_id == order.id for entry in entries)

    export = next(item for item in result.node_results if item.node_id == "export_sales")
    assert export.success is True
    workbook_bytes = export.output["data"]
    sheet = load_workbook(BytesIO(workbook_bytes))["sales"]
    exported_rows = list(sheet.iter_rows(values_only=True))
    assert exported_rows[0][0] == "product_name" or "产品 B" in str(exported_rows)
    flat = " ".join(str(cell) for row in exported_rows for cell in row)
    assert "产品 B" in flat and "1000" in flat
    digest = hashlib.sha256(workbook_bytes).hexdigest()
    assert len(digest) == 64

    with tenant_scope(1):
        paid = payment(
            sales_order_id=order.id,
            amount=Decimal("1000.00"),
            reference=VOUCHER,
            idempotency_key="receipt-s01",
        )
        assert paid["success"] is True
        again = payment(
            sales_order_id=order.id,
            amount=Decimal("1000.00"),
            reference=VOUCHER,
            idempotency_key="receipt-s01",
        )
        assert again.get("idempotent") is True
        over = payment(
            sales_order_id=order.id,
            amount=Decimal("1.00"),
            reference="EXTRA",
            idempotency_key="receipt-s01-extra",
        )
        assert over["success"] is False
    with tenant_scope(1):
        db = factory()
        paid_order = db.query(SalesOrder).filter(SalesOrder.id == order.id).one()
        allocation = db.query(ReceivableAllocation).filter_by(sales_order_id=order.id).one()
        db.close()
    assert Decimal(str(paid_order.paid_amount)) == Decimal("1000")
    assert paid_order.payment_state == "paid"
    assert allocation.request_key == "receipt-s01"
    assert "bank_verified" not in allocation.to_dict()
    mutated = copy.deepcopy(route["payload"])
    mutated["order"]["items"][0]["product_name"] = "产品 D"
    with tenant_scope(1):
        conflict = SalesAppService().execute_closed_loop(mutated)
        assert conflict["success"] is False
        missing = SalesAppService().execute_closed_loop(
            route_normal_mode_message(SENTENCE.replace("测试客户 A", "不存在的客户"))["payload"]
        )
        assert missing["success"] is False

    with tenant_scope(2):
        db = factory()
        try:
            assert db.query(SalesOrder).count() == 0
        finally:
            db.close()

    scarce_sentence = SENTENCE.replace("产品 B", "产品 D")
    with tenant_scope(1):
        scarce = route_normal_mode_message(scarce_sentence)["payload"]
        failed = SalesAppService().execute_closed_loop(scarce)
        assert failed["success"] is False
    assert _available(factory, 1, seed[1]["scarce_id"]) == Decimal("5")

    inactive_sentence = SENTENCE.replace("产品 B", "产品 C")
    with tenant_scope(1):
        inactive = SalesAppService().execute_closed_loop(
            route_normal_mode_message(inactive_sentence)["payload"]
        )
        assert inactive["success"] is False
        assert "停用" in inactive["message"]

    with tenant_scope(1):
        db = factory()
        db.add(Customer(customer_name="测试客户 A"))
        db.commit()
        db.close()
        ambiguous = SalesAppService().execute_closed_loop(
            route_normal_mode_message(SENTENCE.replace("10 件", "1 件").replace("1000", "100"))[
                "payload"
            ]
        )
        # 原句的幂等键不变；换数量会生成新键，重名客户必须拒绝且不改原订单。
        assert ambiguous["success"] is False
    with tenant_scope(1):
        db = factory()
        original = db.query(SalesOrder).filter(SalesOrder.id == order.id).one()
        assert Decimal(str(original.total_amount)) == Decimal("1000")
        db.close()

    with tenant_scope(1):
        quoted = SalesAppService().quote(
            {
                "customer_id": seed[1]["customer_id"],
                "idempotency_key": "partial-delivery",
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": 10,
                        "unit_price": 100,
                        "unit": "件",
                    }
                ],
            }
        )
        assert quoted["success"] is True
        partial_id = int(quoted["data"]["id"])
        assert SalesAppService().confirm(partial_id)["success"] is True
        db = factory()
        partial_item = db.query(SalesOrderItem).filter(SalesOrderItem.order_id == partial_id).one()
        item_id = partial_item.id
        db.close()
        first = FulfillmentService().deliver(
            partial_id,
            item_id,
            6,
            warehouse_id=seed[1]["warehouse_id"],
            idempotency_key="ship-6",
        )
        assert first["success"] is True and first["data"]["partial"] is True
        second = FulfillmentService().deliver(
            partial_id,
            item_id,
            4,
            warehouse_id=seed[1]["warehouse_id"],
            idempotency_key="ship-4",
        )
        assert second["success"] is True and second["data"]["partial"] is False
        replay_ship = FulfillmentService().deliver(
            partial_id,
            item_id,
            4,
            warehouse_id=seed[1]["warehouse_id"],
            idempotency_key="ship-4",
        )
        assert replay_ship.get("idempotent") is True
        over_ship = FulfillmentService().deliver(
            partial_id,
            item_id,
            1,
            warehouse_id=seed[1]["warehouse_id"],
            idempotency_key="ship-over",
        )
        assert over_ship["success"] is False
        returned = FulfillmentService().return_sale(
            partial_id,
            item_id,
            2,
            warehouse_id=seed[1]["warehouse_id"],
            idempotency_key="return-2",
        )
        assert returned["success"] is True
    assert _available(factory, 1, product_id) == Decimal("2")

    with tenant_scope(1):
        staged = SalesAppService().quote(
            {
                "customer_id": seed[1]["customer_id"],
                "idempotency_key": "installment",
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": 10,
                        "unit_price": 100,
                        "unit": "件",
                    }
                ],
            }
        )
        installment_id = int(staged["data"]["id"])
        SalesAppService().confirm(installment_id)
        part = payment(
            sales_order_id=installment_id,
            amount=Decimal("400.00"),
            reference="BANK-400",
            idempotency_key="pay-400",
        )
        rest = payment(
            sales_order_id=installment_id,
            amount=Decimal("600.00"),
            reference="BANK-600",
            idempotency_key="pay-600",
        )
        assert part["success"] and rest["success"]
        db = factory()
        installment = db.query(SalesOrder).filter(SalesOrder.id == installment_id).one()
        assert installment.payment_state == "paid"
        assert Decimal(str(installment.paid_amount)) == Decimal("1000")
        allocation_id = (
            db.query(ReceivableAllocation)
            .filter_by(sales_order_id=installment_id, request_key="pay-400")
            .one()
            .id
        )
        db.close()
        assert refund(allocation_id=allocation_id, reference="REFUND-400")["success"] is True
        db = factory()
        try:
            after_refund = db.query(SalesOrder).filter(SalesOrder.id == installment_id).one()
            assert Decimal(str(after_refund.paid_amount)) == Decimal("600")
            assert after_refund.payment_state == "partial"
        finally:
            db.close()

    with tenant_scope(1):
        hold = SalesAppService().quote(
            {
                "customer_id": seed[1]["customer_id"],
                "idempotency_key": "reserve-cancel",
                "items": [
                    {
                        "product_id": seed[1]["lookalike_id"],
                        "quantity": 4,
                        "unit_price": 100,
                        "unit": "件",
                    }
                ],
            }
        )
        hold_id = int(hold["data"]["id"])
        SalesAppService().confirm(hold_id)
        db = factory()
        hold_item = db.query(SalesOrderItem).filter_by(order_id=hold_id).one()
        hold_item_id = hold_item.id
        db.close()
        reserved = FulfillmentService().reserve(
            hold_id,
            hold_item_id,
            4,
            warehouse_id=seed[1]["warehouse_id"],
            idempotency_key="reserve-4",
        )
        assert reserved["success"] is True
        assert _available(factory, 1, seed[1]["lookalike_id"]) == Decimal("3")
        assert _reserved(factory, 1, seed[1]["lookalike_id"]) == Decimal("4")
        db = factory()
        cancelled = SalesLifecycleService(db, tenant_id=1).cancel(hold_id)
        db.commit()
        assert cancelled.state == "cancel"
        db.close()
        assert _available(factory, 1, seed[1]["lookalike_id"]) == Decimal("7")
        assert _reserved(factory, 1, seed[1]["lookalike_id"]) == Decimal("0")

    rejected = _plan(SENTENCE.replace("产品 B", "产品 D"))
    approval = ApprovalService()
    gated = _engine(approval)
    with tenant_scope(1):
        decision, pending = gated.run(rejected, {"message": "拒绝"}, strategy="interactive")
        assert decision.pending_approval is True and pending is None
        request = approval.get_requests_by_plan(rejected.plan_id)[0]
        assert approval.reject(request.request_id, comment="拒绝") is True
        blocked = gated.resume_after_approval(rejected, {request.request_id: False}, {})
    assert getattr(blocked, "success", False) is False
    assert _available(factory, 1, seed[1]["scarce_id"]) == Decimal("5")
