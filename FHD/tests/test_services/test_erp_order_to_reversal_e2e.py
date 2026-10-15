"""审计 R10（2026-09-05 报告）：ERP「建单→出库→收款→冲销」完整流程端到端验收。

各段此前只有独立测试（lifecycle / fulfillment / payment / invoicing），
本用例把一条真实业务链在同一个数据库、同一张订单上串起来，逐段校验业务数据：

1. 建单：销售订单确认 + 明细 + 初始库存入库；
2. 出库：预留 → 全量交付，库存扣减、出库流水、履行态推进；
3. 收款：开票生成应收凭证 → 全额收款过账（借现金/贷应收），payment_state=paid；
4. 冲销：贷项通知单生成反向凭证、原凭证标记已冲销、订单开票态回退。

任何一段的业务数据不符合预期即失败，证明四段真正贯通而非各自孤立。
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.application.invoicing_service as invoicing_mod
import app.application.payment_service as payment_mod
import app.services.accounting_services as asvc
import app.services.fulfillment_service as fulfill_mod
import app.services.inventory_service as inv_mod
from app.application import invoicing_service, payment_service
from app.application.invoicing_service import invoice as post_invoice
from app.db.base import Base
from app.db.models import (
    InventoryLedger,
    InventoryTransaction,
    JournalEntry,
    Product,
    ReceivableAllocation,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.services.accounting_services import seed_default_chart_of_accounts
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService

ORDER_TOTAL = Decimal("1000.00")
ORDER_QTY = 10


@pytest.fixture(scope="function")
def erp_chain_env():
    """单一内存库 + 全部服务模块 get_db 指向同一持久会话。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    persistent = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )()

    @contextlib.contextmanager
    def test_db():
        yield persistent

    with (
        patch.object(inv_mod, "get_db", test_db),
        patch.object(fulfill_mod, "get_db", test_db),
        patch.object(asvc, "get_db", test_db),
        patch.object(payment_mod, "get_db", test_db),
        patch.object(invoicing_mod, "get_db", test_db),
    ):
        with tenant_scope(1):
            assert seed_default_chart_of_accounts()["success"] is True
            yield persistent
    persistent.close()


def _seed_confirmed_order(db) -> tuple:
    """建单：销售订单（已确认）+ 单明细 + 产品 + 仓库 + 初始库存。"""
    product = Product(
        model_number="E2E-P1",
        name="端到端产品",
        unit="个",
        price=float(ORDER_TOTAL) / ORDER_QTY,
        is_active=1,
    )
    warehouse = Warehouse(code="WH-E2E", name="端到端仓", status="active")
    db.add_all([product, warehouse])
    db.flush()
    order = SalesOrder(
        order_no="SO-E2E-LOOP-001",
        customer_name="端到端客户",
        state="confirmed",
        status="confirmed",
        total_amount=ORDER_TOTAL,
        paid_amount=Decimal("0"),
        payment_state="unpaid",
        invoice_status="not_invoiced",
        created_at=datetime.now(),
    )
    db.add(order)
    db.flush()
    item = SalesOrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        quantity=Decimal(str(ORDER_QTY)),
        ordered_quantity=Decimal(str(ORDER_QTY)),
        reserved_quantity=Decimal("0"),
        delivered_quantity=Decimal("0"),
        returned_quantity=Decimal("0"),
        amount=ORDER_TOTAL,
        unit="个",
        status="pending",
        created_at=datetime.now(),
    )
    db.add(item)
    db.commit()

    inv = InventoryService()
    stocked = inv.inventory_in(product_id=product.id, warehouse_id=warehouse.id, quantity=100)
    assert stocked["success"] is True, stocked.get("message")

    db.refresh(order)
    db.refresh(item)
    return order, item, product, warehouse


def test_full_loop_create_deliver_collect_reverse(erp_chain_env) -> None:
    db = erp_chain_env

    # ---- 1. 建单 ----
    order, item, product, warehouse = _seed_confirmed_order(db)
    assert order.state == "confirmed"
    assert order.payment_state == "unpaid"
    assert order.invoice_status == "not_invoiced"
    with tenant_scope(1):
        ledger = (
            db.query(InventoryLedger)
            .filter_by(product_id=product.id, warehouse_id=warehouse.id)
            .first()
        )
        assert float(ledger.quantity) == 100.0

    # ---- 2. 出库（预留 → 全量交付）----
    with tenant_scope(1):
        fulfill = FulfillmentService()
        reserved = fulfill.reserve(order.id, item.id, ORDER_QTY, warehouse_id=warehouse.id)
        assert reserved["success"] is True, reserved.get("message")
        delivered = fulfill.deliver(order.id, item.id, ORDER_QTY, warehouse_id=warehouse.id)
        assert delivered["success"] is True, delivered.get("message")
        assert delivered["data"]["fulfillment"] == "delivered"

        db.refresh(ledger)
        assert float(ledger.quantity) == 90.0
        assert float(ledger.reserved_quantity) == 0.0
        out_moves = (
            db.query(InventoryTransaction)
            .filter_by(sales_order_item_id=item.id, transaction_type="out")
            .all()
        )
        assert len(out_moves) == 1
        assert float(out_moves[0].quantity) == -float(ORDER_QTY)
        db.refresh(item)
        assert float(item.delivered_quantity) == float(ORDER_QTY)

    # ---- 3. 收款（开票 → 全额收款）----
    with tenant_scope(1):
        inv_result = post_invoice(order.id)
        assert inv_result["success"] is True, inv_result.get("message")
        invoice_entry_id = inv_result["data"]["id"]
        # 同一持久会话内直接读属性（服务层在会话事务中更新，勿 refresh 丢弃 pending）
        assert order.invoice_status == "invoiced"

        pay_result = payment_service.payment(sales_order_id=order.id, amount=ORDER_TOTAL)
        assert pay_result["success"] is True, pay_result.get("message")
        assert pay_result["data"]["status"] == "paid"
        assert order.payment_state == "paid"
        assert Decimal(str(order.paid_amount)) == ORDER_TOTAL
        allocs = db.query(ReceivableAllocation).filter_by(sales_order_id=order.id).all()
        assert len(allocs) == 1
        assert allocs[0].status == "paid"

    # ---- 4. 冲销（贷项通知单反向凭证）----
    with tenant_scope(1):
        cn_result = invoicing_service.credit_note(order.id)
        assert cn_result["success"] is True, cn_result.get("message")
        cn = cn_result["data"]
        assert cn["is_credit_note"] == 1
        assert cn["reversed_of_id"] == invoice_entry_id
        assert cn["balanced"] is True

        original = db.query(JournalEntry).filter(JournalEntry.id == invoice_entry_id).first()
        assert original.reversed_at is not None
        assert order.invoice_status == "credit_note"


def test_loop_refund_after_payment_restores_receivable(erp_chain_env) -> None:
    """收款后退款：分配态回退，证明收款/退款在同一订单上闭环。"""
    db = erp_chain_env
    order, item, product, warehouse = _seed_confirmed_order(db)
    with tenant_scope(1):
        assert post_invoice(order.id)["success"] is True
        pay = payment_service.payment(sales_order_id=order.id, amount=ORDER_TOTAL)
        assert pay["success"] is True

        refund = payment_service.refund(allocation_id=pay["data"]["id"])
        assert refund["success"] is True, refund.get("message")
        allocs = db.query(ReceivableAllocation).filter_by(sales_order_id=order.id).all()
        assert all(a.status == "refunded" for a in allocs)
        assert order.payment_state in ("unpaid", "refunded")
