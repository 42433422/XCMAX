"""
支付服务（收款分配 / 退款 / 冲销）测试（W1-05）

覆盖 ``app/application/payment_service.py``：
- 收款过账 借现金(1001) / 贷应收(1122)
- 写入租户安全 receivable 分配（unpaid/partial/paid/refunded）
- 累计收款超应收被拒
- 同单同金额重复收款幂等
- 全额 → paid
- refund/reversal 生成反向凭证并更新分配为 refunded
- Decimal 安全金额比较与失败回滚

用真实 sqlite（临时文件，连接间共享同一库），通过 patch 覆盖
``accounting_services.get_db`` 与 ``payment_service.get_db`` 指向同一会话；
并暴露会话工厂，便于故障注入后“新建独立会话”验证事务原子性。
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import payment_service as psvc
from app.db.base import Base
from app.db.models import (
    ChartOfAccount,
    Customer,
    JournalEntry,
    ReceivableAllocation,
    SalesOrder,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.services import accounting_services as asvc


@pytest.fixture(scope="function")
def db_session(tmp_path):
    """真实 sqlite 会话（临时文件库，跨连接共享，供新建独立会话验证原子性）。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_payment_service.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    # 暴露会话工厂：故障注入后打开“全新会话”证明无半成品落库
    db.info["session_factory"] = SessionLocal
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _override_get_db(monkeypatch, db_session):
    """把 accounting_services 与 payment_service 的 get_db 指向同一内存库会话。"""

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

    def test_payment_creates_balanced_journal_entry(self, db_session):
        """收款生成平衡凭证：借现金1001 / 贷应收1122，且应收行绑定 partner。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            result = psvc.payment(
                sales_order_id=order.id,
                amount=Decimal("400.00"),
                partner_id=7,
                partner_name="租户客户",
            )
            assert result["success"] is True
            entry_id = result["data"]["journal_entry_id"]
            entry = db_session.query(JournalEntry).filter_by(id=entry_id).first()
            assert entry is not None
            assert entry.reference_type == "payment"
            assert entry.reference_id == order.id
            # 借贷平衡
            assert entry.debit_total == entry.credit_total == Decimal("400.00")
            codes = {(ln.account_code, float(ln.debit), float(ln.credit)) for ln in entry.lines}
            assert ("1001", 400.0, 0.0) in codes
            assert ("1122", 0.0, 400.0) in codes
            # 应收行绑定 partner
            recv_line = [ln for ln in entry.lines if ln.account_code == "1122"][0]
            assert recv_line.partner_id == 7


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

    def test_refund_already_refunded_is_idempotent(self, db_session):
        """重复退款幂等成功：不生成第二张退款凭证或第二条冲销分配。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            first = psvc.refund(allocation_id=paid["data"]["id"])
            assert first["success"] is True
            second = psvc.refund(allocation_id=paid["data"]["id"])
            assert second["success"] is True
            assert second.get("idempotent") is True

            # 仅一张收款凭证 + 一张退款（反向）凭证；冲销分配仅一条
            assert db_session.query(JournalEntry).count() == 2
            reversals = (
                db_session.query(ReceivableAllocation).filter_by(reference_type="reversal").all()
            )
            assert len(reversals) == 1
            refund_entries = db_session.query(JournalEntry).filter_by(reference_type="refund").all()
            assert len(refund_entries) == 1

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

    def test_full_refund_of_only_payment_returns_order_to_unpaid(self, db_session):
        """唯一一笔收款全额退款 → 订单回到 unpaid，且产生冲销分配行。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("1000.00"))
            assert paid["data"]["status"] == "paid"
            psvc.refund(allocation_id=paid["data"]["id"])

            db_session.refresh(order)
            assert order.paid_amount == Decimal("0.00")
            assert order.payment_state == "unpaid"
            # 两条分配：原始 refunded + 冲销 reversal
            allocs = db_session.query(ReceivableAllocation).filter_by(sales_order_id=order.id).all()
            assert len(allocs) == 2
            reversal = [a for a in allocs if a.reference_type == "reversal"][0]
            assert reversal.status == "refunded"
            assert reversal.reversed_of_id == paid["data"]["id"]


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


class TestTenantIsolation:
    def test_tenant2_cannot_see_tenant1_allocations(self, db_session):
        """跨租户隔离：租户 2 查询不到租户 1 的收款分配。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            assert len(db_session.query(ReceivableAllocation).all()) == 1
        with tenant_scope(2):
            assert db_session.query(ReceivableAllocation).all() == []

    def test_tenant2_cannot_refund_tenant1_allocation(self, db_session):
        """跨租户隔离：租户 2 无法退款租户 1 的收款分配。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            alloc_id = paid["data"]["id"]
        with tenant_scope(2):
            result = psvc.refund(allocation_id=alloc_id)
            assert result["success"] is False
            assert "分配不存在" in result["message"]


def _fail_journal_entry(*_args, **_kwargs):
    """故障注入：模拟记账（create_journal_entry）返回失败。"""
    return {"success": False, "message": "注入：记账失败"}


def _raise_on_alloc_add(original_add):
    """故障注入工厂：仅让分配（ReceivableAllocation）写入时抛异常。

    其它对象（如 JournalEntry / JournalEntryLine）仍委托给原始 ``Session.add``，
    从而保证故障触发点位于“凭证已 flush 之后”的分配落库环节。
    """

    def _inject(obj):
        if isinstance(obj, ReceivableAllocation):
            raise RuntimeError("注入：分配写入失败")
        return original_add(obj)

    return _inject


class TestFailureInjection:
    """故障注入：验证 ``with get_db()`` 上下文持有的事务原子性。

    收款/退款均与记账凭证在同一事务内（``create_journal_entry(..., db=db)``
    不自行提交，由 ``with get_db()`` 上下文在成功退出时统一提交、异常时回滚）。
    故障注入在凭证已 flush 之后触发（分配 add 失败），异常逃出上下文，随后
    “新建独立会话”证明无凭证 / 无分配 / 无退款状态变更 / 无订单金额与支付状态落库。
    """

    def test_payment_rolls_back_when_journal_entry_fails(self, db_session, monkeypatch):
        """记账失败（create_journal_entry 返回失败）→ 无任何残留。"""
        monkeypatch.setattr(psvc, "create_journal_entry", _fail_journal_entry)
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            result = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            assert result["success"] is False
            assert db_session.query(ReceivableAllocation).count() == 0
            assert db_session.query(JournalEntry).count() == 0
            db_session.refresh(order)
            assert order.paid_amount == Decimal("0.00")
            assert order.payment_state == "unpaid"

    def test_payment_atomic_when_allocation_add_fails(self, db_session, monkeypatch):
        """凭证已 flush 后分配 add 失败 → 异常逃出上下文，整体回滚，无半成品落库。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
        monkeypatch.setattr(db_session, "add", _raise_on_alloc_add(db_session.add))
        with tenant_scope(1):
            with pytest.raises(RuntimeError):
                psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
        # 模拟生产 ``get_db`` 在异常逃出时回滚，随后新建独立会话验证原子性
        db_session.rollback()
        fresh = db_session.info["session_factory"]()
        try:
            with tenant_scope(1):
                assert fresh.query(JournalEntry).count() == 0
                assert fresh.query(ReceivableAllocation).count() == 0
                order_fresh = fresh.query(SalesOrder).filter_by(id=order.id).first()
                assert order_fresh.paid_amount == Decimal("0.00")
                assert order_fresh.payment_state == "unpaid"
        finally:
            fresh.close()

    def test_refund_rolls_back_when_journal_entry_fails(self, db_session, monkeypatch):
        """退款记账失败 → 原分配保持未退款，无冲销行残留。"""
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            alloc_id = paid["data"]["id"]
        monkeypatch.setattr(psvc, "create_journal_entry", _fail_journal_entry)
        with tenant_scope(1):
            result = psvc.refund(allocation_id=alloc_id)
            assert result["success"] is False
            original = db_session.query(ReceivableAllocation).filter_by(id=alloc_id).first()
            assert original.status != "refunded"
            assert (
                db_session.query(ReceivableAllocation).filter_by(reference_type="reversal").count()
                == 0
            )

    def test_refund_atomic_when_reversal_add_fails(self, db_session, monkeypatch):
        """退款凭证已 flush 后冲销分配 add 失败 → 异常逃出上下文，整体回滚。

        无第二张退款凭证、无冲销分配、原分配不被标记 refunded，订单金额/状态不变。
        """
        with tenant_scope(1):
            order = _make_order(db_session, Decimal("1000.00"))
            paid = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"))
            alloc_id = paid["data"]["id"]
            # get_db 被 patch 为不提交；显式提交以模拟“收款已成功落库”的前置状态
            db_session.commit()
        monkeypatch.setattr(db_session, "add", _raise_on_alloc_add(db_session.add))
        with tenant_scope(1):
            with pytest.raises(RuntimeError):
                psvc.refund(allocation_id=alloc_id)
        db_session.rollback()
        fresh = db_session.info["session_factory"]()
        try:
            with tenant_scope(1):
                # 仅保留原始收款凭证；退款凭证未落库
                assert fresh.query(JournalEntry).count() == 1
                # 仅原始收款分配；无冲销分配，且原分配未被标记 refunded
                allocs = fresh.query(ReceivableAllocation).all()
                assert len(allocs) == 1
                assert allocs[0].status != "refunded"
                assert (
                    fresh.query(ReceivableAllocation).filter_by(reference_type="reversal").count()
                    == 0
                )
                # 订单金额与支付状态未变（仍为 400 / partial）
                order_fresh = fresh.query(SalesOrder).filter_by(id=order.id).first()
                assert order_fresh.paid_amount == Decimal("400.00")
                assert order_fresh.payment_state == "partial"
        finally:
            fresh.close()


# ---------------------------------------------------------------------------
# 调用方共享会话所有权（W1-10 Shared Session Ownership Refactor）
# payment(..., db=session)：不自开 get_db、不 commit/rollback/close，
# 凭证与分配跨会话可见性受调用方事务控制。
# ---------------------------------------------------------------------------
@pytest.fixture(scope="function")
def owner_db(tmp_path):
    """文件落盘 sqlite：跨会话可见性断言需同一文件库多个连接。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'payment_owner.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_factory()
    db.info["session_factory"] = session_factory
    try:
        yield db
    finally:
        db.close()


def _owner_order(db, total: Decimal = Decimal("1000.00")) -> SalesOrder:
    with tenant_scope(1):
        for spec in asvc.DEFAULT_CHART_OF_ACCOUNTS:
            if db.query(ChartOfAccount).filter(ChartOfAccount.code == spec["code"]).first():
                continue
            db.add(ChartOfAccount(**spec))
        customer = Customer(customer_name="测试客户P")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no="SO-OWN-PAY-0001",
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


class TestPaymentCallerOwnedSession:
    """payment 在调用方会话内执行：不 commit/rollback/close，跨会话可见性受调用方事务控制。"""

    def test_payment_uses_session_never_commits_rollbacks_closes(self, owner_db):
        db = owner_db
        order = _owner_order(db)
        fresh = db.info["session_factory"]()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    asvc, "get_db", lambda: (_ for _ in ()).throw(AssertionError("no get_db"))
                )
                mp.setattr(
                    psvc, "get_db", lambda: (_ for _ in ()).throw(AssertionError("no get_db"))
                )
                with tenant_scope(1):
                    result = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"), db=db)
            assert result["success"] is True, result.get("message")
            # 同会话 flush 后可见
            assert (
                db.query(ReceivableAllocation).filter_by(sales_order_id=order.id).first()
                is not None
            )
            # caller 提交前，新会话不可见
            assert (
                fresh.query(ReceivableAllocation).filter_by(sales_order_id=order.id).first() is None
            )
            db.commit()
            fresh_alloc = (
                fresh.query(ReceivableAllocation).filter_by(sales_order_id=order.id).first()
            )
            assert fresh_alloc is not None
            fresh_order = fresh.query(SalesOrder).filter_by(id=order.id).first()
            assert fresh_order.paid_amount == Decimal("400.00")
            assert fresh_order.payment_state == "partial"
        finally:
            db.close()
            fresh.close()

    def test_payment_caller_rollback_removes(self, owner_db):
        db = owner_db
        order = _owner_order(db)
        fresh = db.info["session_factory"]()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(
                    asvc, "get_db", lambda: (_ for _ in ()).throw(AssertionError("no get_db"))
                )
                mp.setattr(
                    psvc, "get_db", lambda: (_ for _ in ()).throw(AssertionError("no get_db"))
                )
                with tenant_scope(1):
                    result = psvc.payment(sales_order_id=order.id, amount=Decimal("400.00"), db=db)
            assert result["success"] is True
            db.rollback()
            assert (
                fresh.query(ReceivableAllocation).filter_by(sales_order_id=order.id).first() is None
            )
            fresh_order = fresh.query(SalesOrder).filter_by(id=order.id).first()
            assert fresh_order.paid_amount == Decimal("0.00")
            assert fresh_order.payment_state == "unpaid"
        finally:
            db.close()
            fresh.close()
