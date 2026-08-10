"""
开票/贷项通知单 & 记账服务测试（ODOO-W1-04）

覆盖 ``app/application/invoicing_service.py`` + ``app/services/accounting_services.py`` 新增 API：

- ``invoice()`` 生成平衡凭证 借应收账款(1122, partner) / 贷主营业务收入(6001)，
  ``reference_type='sale'``、``reference_id=order_id``。
- invoice status 独立计算（可先开票后发货）。
- ``credit_note()`` 经 ``reversed_of_id`` 生成反向凭证。
- 重复 ``invoice()`` 幂等，不重复生成。
- 复用通用平衡记账 API ``create_journal_entry``。

用真实 sqlite :memory:，并通过 patch 覆盖 ``get_db`` 指向内存库。
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import invoicing_service
from app.db.base import Base
from app.db.models import Customer, JournalEntry, Product, SalesOrder, SalesOrderItem
from app.services import accounting_services as svc


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
    """把 accounting_services 与 invoicing_service 的 get_db 都覆盖为内存库会话。"""

    @contextmanager
    def _get_db():
        yield db_session

    monkeypatch.setattr(svc, "get_db", _get_db)
    monkeypatch.setattr(invoicing_service, "get_db", _get_db)
    yield


def _make_order(db_session, total: float = 1000.0) -> SalesOrder:
    """创建一张报价态（未发货、未开票）的销售订单。"""
    customer = Customer(customer_name="客户A")
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)

    product = Product(name="产品X", price=100.0, unit="个", is_active=1)
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    order = SalesOrder(
        order_no="SO-W104-0001",
        customer_id=customer.id,
        customer_name=customer.customer_name,
        state="quote",
        status="quote",
        invoice_status="not_invoiced",
        payment_state="unpaid",
        total_amount=total,
        paid_amount=0,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    item = SalesOrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        quantity=10,
        ordered_quantity=10,
        unit="个",
        unit_price=100.0,
        amount=total,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(order)
    return order


def _sale_entries(db_session, order_id: int) -> list[JournalEntry]:
    return (
        db_session.query(JournalEntry)
        .filter(
            JournalEntry.reference_type == "sale",
            JournalEntry.reference_id == int(order_id),
        )
        .all()
    )


class TestInvoice:
    def test_invoice_creates_balanced_sale_entry(self, db_session):
        """开票生成 借应收(1122, partner) / 贷收入(6001) 平衡凭证。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)

        result = invoicing_service.invoice(order.id)
        assert result["success"] is True, result.get("message")

        entry = result["data"]
        assert entry["status"] == "posted"
        assert entry["reference_type"] == "sale"
        assert entry["reference_id"] == order.id
        assert entry["balanced"] is True
        lines = {l["account_code"]: l for l in entry["lines"]}
        assert lines["1122"]["debit"] == 1000.0
        assert lines["1122"]["credit"] == 0.0
        assert lines["1122"]["partner_id"] == order.customer_id
        assert lines["1122"]["partner_name"] == order.customer_name
        assert lines["6001"]["credit"] == 1000.0
        assert lines["6001"]["debit"] == 0.0

    def test_invoice_updates_invoice_status(self, db_session):
        """开票后订单 invoice_status 变为 invoiced。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)

        invoicing_service.invoice(order.id)

        reloaded = db_session.query(SalesOrder).filter(SalesOrder.id == order.id).first()
        assert reloaded.invoice_status == "invoiced"

    def test_invoice_status_independent_may_precede_delivery(self, db_session):
        """invoice status 独立：未发货（fulfillment 为空）也可开票。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)
        # 未发货：delivered_quantity 为 0
        item = order.items[0]
        assert item.delivered_quantity == 0

        result = invoicing_service.invoice(order.id)
        assert result["success"] is True, result.get("message")
        reloaded = db_session.query(SalesOrder).filter(SalesOrder.id == order.id).first()
        assert reloaded.invoice_status == "invoiced"
        assert reloaded.fulfillment_state() == "unfulfilled"

    def test_duplicate_invoice_is_idempotent(self, db_session):
        """重复开票幂等：不重复生成凭证。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)

        first = invoicing_service.invoice(order.id)
        assert first["success"] is True

        second = invoicing_service.invoice(order.id)
        assert second["success"] is True
        assert second.get("duplicate") is True
        assert second["entry_id"] == first["data"]["id"]

        entries = _sale_entries(db_session, order.id)
        assert len(entries) == 1

    def test_invoice_missing_order(self, db_session):
        """订单不存在返回失败。"""
        svc.seed_default_chart_of_accounts()
        result = invoicing_service.invoice(999999)
        assert result["success"] is False


class TestCreditNote:
    def test_credit_note_creates_reversing_entry(self, db_session):
        """贷项通知单经 reversed_of_id 关联原销售凭证，方向反转且平衡。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)
        inv = invoicing_service.invoice(order.id)
        invoice_id = inv["data"]["id"]

        result = invoicing_service.credit_note(order.id)
        assert result["success"] is True, result.get("message")

        cn = result["data"]
        assert cn["status"] == "posted"
        assert cn["reversed_of_id"] == invoice_id
        assert cn["is_credit_note"] == 1
        assert cn["balanced"] is True
        lines = {l["account_code"]: l for l in cn["lines"]}
        assert lines["1122"]["credit"] == 1000.0
        assert lines["1122"]["debit"] == 0.0
        assert lines["6001"]["debit"] == 1000.0
        assert lines["6001"]["credit"] == 0.0

    def test_credit_note_marks_original_reversed_and_status(self, db_session):
        """原凭证被标记已冲销，订单开票状态变为 credit_note。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)
        inv = invoicing_service.invoice(order.id)
        invoice_id = inv["data"]["id"]

        invoicing_service.credit_note(order.id)

        original = db_session.query(JournalEntry).filter(JournalEntry.id == invoice_id).first()
        assert original.reversed_at is not None
        reloaded = db_session.query(SalesOrder).filter(SalesOrder.id == order.id).first()
        assert reloaded.invoice_status == "credit_note"

    def test_credit_note_requires_invoice_first(self, db_session):
        """订单未开票时不能生成贷项通知单。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)

        result = invoicing_service.credit_note(order.id)
        assert result["success"] is False


class TestReusableBalancedApi:
    def test_create_sale_invoice_entry_reuses_balanced_api(self, db_session):
        """可复用 API 直接生成销售开票平衡凭证。"""
        svc.seed_default_chart_of_accounts()
        result = svc.create_sale_invoice_entry(
            7, partner_id=101, partner_name="客户A", amount=500.0
        )
        assert result["success"] is True, result.get("message")
        entry = result["data"]
        assert entry["reference_type"] == "sale"
        assert entry["reference_id"] == 7
        assert entry["balanced"] is True

    def test_create_credit_note_entry_links_via_reversed_of(self, db_session):
        """可复用 API 生成贷项通知单并经 reversed_of_id 关联。"""
        svc.seed_default_chart_of_accounts()
        original = svc.create_sale_invoice_entry(
            8, partner_id=102, partner_name="客户B", amount=300.0
        )
        assert original["success"] is True
        original_id = original["data"]["id"]

        result = svc.create_credit_note_entry(original_id, order_id=8)
        assert result["success"] is True, result.get("message")
        cn = result["data"]
        assert cn["reversed_of_id"] == original_id
        assert cn["balanced"] is True


class TestAtomicRollback:
    """失败注入：最终事务失败时整体回滚，不留任何半成品业务状态。"""

    def _install_failing_commit(self, monkeypatch, db_session):
        """让 get_db 变为『退出时提交』，并在提交时注入失败后回滚。"""

        @contextmanager
        def _failing_get_db():
            try:
                yield db_session
                db_session.commit()
            except Exception:
                db_session.rollback()
                raise

        monkeypatch.setattr(svc, "get_db", _failing_get_db)
        monkeypatch.setattr(invoicing_service, "get_db", _failing_get_db)

        def _boom(*args, **kwargs):
            db_session.rollback()
            raise RuntimeError("injected final transaction failure")

        monkeypatch.setattr(db_session, "commit", _boom)

    def test_invoice_rolls_back_entries_and_status_on_final_failure(self, db_session, monkeypatch):
        """开票最终事务失败 → 回滚：零新增凭证，订单开票状态不变。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)
        self._install_failing_commit(monkeypatch, db_session)

        with pytest.raises(RuntimeError):
            invoicing_service.invoice(order.id)

        assert db_session.query(JournalEntry).count() == 0
        reloaded = db_session.query(SalesOrder).filter(SalesOrder.id == order.id).first()
        assert reloaded.invoice_status == "not_invoiced"

    def test_credit_note_rolls_back_entries_and_original_on_final_failure(
        self, db_session, monkeypatch
    ):
        """贷项通知单最终事务失败 → 回滚：零新增凭证，原凭证未冲销，开票状态不变。"""
        svc.seed_default_chart_of_accounts()
        order = _make_order(db_session)
        inv = invoicing_service.invoice(order.id)
        assert inv["success"] is True
        invoice_id = inv["data"]["id"]
        db_session.commit()  # 固化基线发票，仅回滚后续失败事务

        self._install_failing_commit(monkeypatch, db_session)

        with pytest.raises(RuntimeError):
            invoicing_service.credit_note(order.id)

        assert db_session.query(JournalEntry).count() == 1
        original = db_session.query(JournalEntry).filter(JournalEntry.id == invoice_id).first()
        assert original.reversed_at is None
        reloaded = db_session.query(SalesOrder).filter(SalesOrder.id == order.id).first()
        assert reloaded.invoice_status == "invoiced"
