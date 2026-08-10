"""销售生命周期命令模块（W1-02）测试。

覆盖：正向推进、非法回退被拒、取消在已履行/已开票后被拒、幂等、
跨维度独立（state 变更不触碰履行/开票/收款）、租户作用域、Decimal 精确性。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.sales_lifecycle_service import (
    SalesLifecycleCancelBlocked,
    SalesLifecycleInvalidTransition,
    SalesLifecycleNotFound,
    SalesLifecycleService,
    SalesLifecycleTenantMismatch,
)
from app.db.base import Base
from app.db.models import SalesOrder, SalesOrderItem

_FIXED_DAY = date(2026, 8, 10)


@pytest.fixture(scope="function")
def test_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_order(
    db,
    *,
    state: str = "quote",
    tenant_id: int = 1,
    ordered: Decimal = Decimal("10"),
    delivered: Decimal = Decimal("0"),
    returned: Decimal = Decimal("0"),
    invoice_status: str = "not_invoiced",
    payment_state: str = "unpaid",
    order_no: str = "SO-LC-0001",
) -> SalesOrder:
    order = SalesOrder(
        order_no=order_no,
        state=state,
        tenant_id=tenant_id,
        invoice_status=invoice_status,
        payment_state=payment_state,
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
    )
    item = SalesOrderItem(
        product_name="产品X",
        quantity=10,
        unit="个",
        unit_price=Decimal("100.00"),
        amount=Decimal("1000.00"),
        ordered_quantity=ordered,
        delivered_quantity=delivered,
        returned_quantity=returned,
    )
    order.items.append(item)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _service(db, tenant_id=1):
    return SalesLifecycleService(db, tenant_id=tenant_id, now=_FIXED_DAY)


# --------------------------------------------------------------------- #
# 正向推进
# --------------------------------------------------------------------- #
def test_draft_quote_sent_confirmed_progression(test_session):
    order = _make_order(test_session, state="draft")
    svc = _service(test_session)

    svc.quote(order.id)
    test_session.commit()
    assert order.state == "quote"
    assert order.quote_date == _FIXED_DAY

    svc.send_quote(order.id)
    test_session.commit()
    assert order.state == "sent"
    assert order.sent_date == _FIXED_DAY

    svc.confirm(order.id)
    test_session.commit()
    assert order.state == "confirmed"
    assert order.confirm_date == _FIXED_DAY


def test_quote_to_confirmed_direct_is_legal(test_session):
    order = _make_order(test_session, state="quote")
    svc = _service(test_session)

    svc.confirm(order.id)
    test_session.commit()
    assert order.state == "confirmed"
    assert order.confirm_date == _FIXED_DAY


def test_cancel_unfulfilled_uninvoiced(test_session):
    order = _make_order(test_session, state="sent")
    svc = _service(test_session)

    svc.cancel(order.id)
    test_session.commit()
    assert order.state == "cancel"
    assert order.cancel_date == _FIXED_DAY


# --------------------------------------------------------------------- #
# 非法 / 回退被拒（fail-closed）
# --------------------------------------------------------------------- #
def test_confirmed_to_sent_rollback_rejected(test_session):
    order = _make_order(test_session, state="confirmed")
    svc = _service(test_session)

    with pytest.raises(SalesLifecycleInvalidTransition):
        svc.send_quote(order.id)
    test_session.rollback()
    assert order.state == "confirmed"  # 未被改动


def test_sent_to_quote_rollback_rejected(test_session):
    order = _make_order(test_session, state="sent")
    svc = _service(test_session)

    with pytest.raises(SalesLifecycleInvalidTransition):
        svc.quote(order.id)
    test_session.rollback()
    assert order.state == "sent"


def test_cancel_from_cancel_then_transition_guard(test_session):
    # cancel 是终态：从 cancel 不能再次 confirm
    order = _make_order(test_session, state="cancel")
    svc = _service(test_session)
    with pytest.raises(SalesLifecycleInvalidTransition):
        svc.confirm(order.id)
    test_session.rollback()
    assert order.state == "cancel"


# --------------------------------------------------------------------- #
# 取消在已履行 / 已开票后被拒（跨维度隔离）
# --------------------------------------------------------------------- #
def test_cancel_blocked_after_partial_fulfillment(test_session):
    order = _make_order(test_session, state="sent", delivered=Decimal("5"))
    svc = _service(test_session)

    assert order.fulfillment_state() == "partial"
    with pytest.raises(SalesLifecycleCancelBlocked):
        svc.cancel(order.id)
    test_session.rollback()
    assert order.state == "sent"


def test_cancel_blocked_after_full_delivery(test_session):
    order = _make_order(test_session, state="confirmed", delivered=Decimal("10"))
    svc = _service(test_session)

    assert order.fulfillment_state() == "delivered"
    with pytest.raises(SalesLifecycleCancelBlocked):
        svc.cancel(order.id)
    test_session.rollback()
    assert order.state == "confirmed"


def test_cancel_blocked_after_invoicing(test_session):
    order = _make_order(test_session, state="confirmed", invoice_status="invoiced")
    svc = _service(test_session)

    with pytest.raises(SalesLifecycleCancelBlocked):
        svc.cancel(order.id)
    test_session.rollback()
    assert order.state == "confirmed"


def test_cancel_blocked_when_invoiced_but_unfulfilled(test_session):
    # 开票独立于履行：即使未发货，已开票也不可取消
    order = _make_order(test_session, state="sent", invoice_status="invoiced")
    svc = _service(test_session)

    with pytest.raises(SalesLifecycleCancelBlocked):
        svc.cancel(order.id)
    test_session.rollback()
    assert order.state == "sent"


# --------------------------------------------------------------------- #
# 幂等
# --------------------------------------------------------------------- #
def test_confirm_idempotent(test_session):
    order = _make_order(test_session, state="confirmed")
    svc = _service(test_session)

    result = svc.confirm(order.id)
    test_session.commit()
    assert result.state == "confirmed"


def test_cancel_idempotent(test_session):
    order = _make_order(test_session, state="cancel")
    svc = _service(test_session)

    result = svc.cancel(order.id)
    test_session.commit()
    assert result.state == "cancel"


# --------------------------------------------------------------------- #
# 跨维度独立：state 变更不触碰履行/开票/收款
# --------------------------------------------------------------------- #
def test_state_changes_do_not_touch_other_dimensions(test_session):
    order = _make_order(
        test_session,
        state="draft",
        invoice_status="invoiced",
        payment_state="paid",
        delivered=Decimal("10"),
    )
    svc = _service(test_session)

    svc.quote(order.id)
    svc.send_quote(order.id)
    svc.confirm(order.id)
    test_session.commit()

    assert order.state == "confirmed"
    # 其他维度保持不变
    assert order.invoice_status == "invoiced"
    assert order.payment_state == "paid"
    assert order.fulfillment_state() == "delivered"
    assert order.quote_date == _FIXED_DAY
    assert order.sent_date == _FIXED_DAY
    assert order.confirm_date == _FIXED_DAY
    assert order.cancel_date is None


def test_confirm_keeps_payment_state_independent(test_session):
    order = _make_order(test_session, state="sent", payment_state="partial")
    svc = _service(test_session)

    svc.confirm(order.id)
    test_session.commit()
    assert order.state == "confirmed"
    assert order.payment_state == "partial"


# --------------------------------------------------------------------- #
# 租户作用域（fail-closed）
# --------------------------------------------------------------------- #
def test_tenant_mismatch_rejected(test_session):
    order = _make_order(test_session, state="quote", tenant_id=1)
    svc = _service(test_session, tenant_id=2)

    with pytest.raises(SalesLifecycleTenantMismatch):
        svc.confirm(order.id)
    test_session.rollback()
    assert order.state == "quote"


def test_not_found_rejected(test_session):
    svc = _service(test_session)
    with pytest.raises(SalesLifecycleNotFound):
        svc.confirm(999999)


# --------------------------------------------------------------------- #
# Decimal 精确性：履行数量以 Decimal 参与计算
# --------------------------------------------------------------------- #
def test_decimal_fulfillment_blocks_cancel(test_session):
    # 以 Decimal 构造的 delivered 数量，精确触发 partial 阻止取消
    order = _make_order(
        test_session,
        state="sent",
        ordered=Decimal("10"),
        delivered=Decimal("3.5"),
    )
    svc = _service(test_session)
    assert order.fulfillment_state() == "partial"
    with pytest.raises(SalesLifecycleCancelBlocked):
        svc.cancel(order.id)
    test_session.rollback()


def test_decimal_zero_delivered_allows_cancel(test_session):
    order = _make_order(
        test_session,
        state="sent",
        ordered=Decimal("10"),
        delivered=Decimal("0"),
    )
    svc = _service(test_session)
    assert order.fulfillment_state() == "unfulfilled"
    svc.cancel(order.id)
    test_session.commit()
    assert order.state == "cancel"
