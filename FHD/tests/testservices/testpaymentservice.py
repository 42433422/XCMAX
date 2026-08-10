"""
支付服务（收款分配 / 退款 / 冲销）测试（W1-05）

覆盖 ``app/application/paymentservice.py``：
- 收款过账 借现金(1001) / 贷应收(1122)
- 写入租户安全 receivable 分配（unpaid/partial/paid/refunded）
- 累计收款超应收被拒
- 同单同金额重复收款幂等
- 全额 → paid
- refund/reversal 生成反向凭证并更新分配为 refunded
- Decimal 安全金额比较与失败回滚

用真实 sqlite :memory:，通过 patch 覆盖 ``accounting_services.get_db`` 与
``paymentservice.get_db`` 指向同一内存库会话。
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import paymentservice as psvc
from app.db.base import Base
from app.db.models import Customer, ReceivableAllocation, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope
from app.services import accounting_services as asvc


@pytest.fixture(scope="function")
def db_session():
    """真实 sqlite 内存库会话。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _override_get_db(monkeypatch, db_session):
    """把 accounting_services 与 paymentservice 的 get_db 指向同一内存库会话。"""

    @contextmanager
    def _get_db():
        yield db_session

    monkeypatch.setattr(asvc, "get_db", _get_db)
    monkeypatch.setattr(psvc, "get_db", _get_db)
    yield


def _make_order(db, total, order_no: str = "SO-TEST-0001") -> SalesOrder:
    customer = Customer(customer_name="测试客户")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    order = SalesOrder(
        order_no=order_no,
        customer_id=customer.id,
        customer_name=customer.customer_name,
        state="confirmed",
        status="confirmed",
        total_amount=total,
        paid_amount=0,
        payment_state="unpaid",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _allocations(db, order_id: int):
    return db.query(ReceivableAllocation).filter_by(sales_order_id=order_id).all()


class TestPayment:
    def test_payment_posts_cash_and_receivable(self, db_session):
        """收款过账 借现金1001 / 贷应收1122，并写入分配。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            result = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            assert result["success"] is True, result.get("message")

            alloc = result["data"]
            assert alloc["sales_order_id"] == order.id
            assert alloc["status"] == "partial"
            assert alloc["journal_entry_id"] is not None
            assert alloc["line_id"] is not None

    def test_full_payment_is_paid(self, db_session):
        """全额收款 → paid。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("500.00"))
            result = psvc.payment(sales_order_id=order.id, amount=Decimal("500.00"))
            assert result["success"] is True
            assert result["data"]["status"] == "paid"

            db_session.refresh(order)
            assert order.payment_state == "paid"

    def test_partial_payments_accumulate_to_paid(self, db_session):
        """多笔部分收款累计到全额 → paid，且各自分配保留。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            r1 = psvc.payment(sales_order_id=order.id, amount=Decimal("600.00"))
            r2 = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            assert r1["success"] is True and r1["data"]["status"] == "partial"
            assert r2["success"] is True and r2["data"]["status"] == "paid"

            allocations = _allocations(db_session, order.id)
            assert len(allocations) == 2
            db_session.refresh(order)
            assert order.paid_amount == Decimal("1000.00")
            assert order.payment_state == "paid"

    def test_overpayment_rejected(self, db_session):
        """累计收款超应收被拒。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            psvc.payment(sales_order_id=order.id, amount=Decimal("900.00"))
            result = psvc.payment(sales_order_id=order.id, amount=Decimal("200.00"))
            assert result["success"] is False
            assert "超应收" in result["message"]

            # 超收被拒后不新增分配
            assert len(_allocations(db_session, order.id)) == 1

    def test_same_order_same_amount_idempotent(self, db_session):
        """同单同金额重复收款幂等：不重复生成分配。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            first = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            second = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            assert first["success"] is True
            assert second["success"] is True
            assert second.get("idempotent") is True

            allocations = _allocations(db_session, order.id)
            assert len(allocations) == 1

    def test_zero_amount_rejected(self, db_session):
        """金额必须大于 0。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("100.00"))
            assert psvc.payment(sales_order_id=order.id, amount=0)["success"] is False
            assert psvc.payment(sales_order_id=order.id, amount=Decimal("-1"))["success"] is False

    def test_missing_order(self, db_session):
        """订单不存在返回失败。"""
        with tenant_scope(1):
            result = psvc.payment(sales_order_id=999999, amount=Decimal("10"))
            assert result["success"] is False


class TestRefund:
    def test_refund_posts_reverse_and_marks_refunded(self, db_session):
        """退款生成反向凭证并更新分配为 refunded。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            alloc_id = paid["data"]["id"]
            original_entry_id = paid["data"]["journal_entry_id"]

            result = psvc.refund(allocation_id=alloc_id)
            assert result["success"] is True, result.get("message")
            assert result["data"]["status"] == "refunded"
            # 冲销分配经 reversed_of_id 关联原始分配，并承载反向凭证
            assert result["data"]["reversed_of_id"] == alloc_id
            assert result["data"]["journal_entry_id"] is not None
            assert result["data"]["journal_entry_id"] != original_entry_id
            # 原始分配亦标记为 refunded
            original = db_session.query(ReceivableAllocation).filter_by(id=alloc_id).first()
            assert original is not None
            assert original.status == "refunded"

            db_session.refresh(order)
            assert order.paid_amount == Decimal("0.00")
            assert order.payment_state == "unpaid"

    def test_refund_missing_allocation(self, db_session):
        """分配不存在返回失败。"""
        with tenant_scope(1):
            assert psvc.refund(allocation_id=999999)["success"] is False

    def test_refund_already_refunded_rejected(self, db_session):
        """重复退款被拒。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            psvc.refund(allocation_id=paid["data"]["id"])
            second = psvc.refund(allocation_id=paid["data"]["id"])
            assert second["success"] is False
            assert "不能重复冲销" in second["message"]

    def test_partial_refund_recomputes_state(self, db_session):
        """部分退款后订单状态正确回落。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            psvc.payment(sales_order_id=order.id, amount=Decimal("600.00"))
            refund_alloc = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            psvc.refund(allocation_id=refund_alloc["data"]["id"])

            db_session.refresh(order)
            assert order.paid_amount == Decimal("600.00")
            assert order.payment_state == "partial"


class TestDecimalSafety:
    def test_decimal_precision_kept(self, db_session):
        """金额比较使用 Decimal，避免浮点误差。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("0.30"))
            # 0.1 + 0.2 浮点会略大于 0.3，Decimal 应精确判为 paid
            psvc.payment(sales_order_id=order.id, amount=Decimal("0.10"))
            result = psvc.payment(sales_order_id=order.id, amount=Decimal("0.20"))
            assert result["success"] is True
            assert result["data"]["status"] == "paid"
