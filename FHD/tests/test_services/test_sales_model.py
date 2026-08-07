"""
销售数据模型（Sales-to-Payment 闭环）单元测试

覆盖 Task 2（absorb-odoo18-erp-agent）：
- 建单(quote) -> 确认(confirmed) -> 发货(delivered) -> 开票(invoiced) -> 收款(paid) 状态推进闭环
- 明细行交付/开票/收款数量推进
- 非法状态回退被拒绝
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import (
    SALES_ORDER_STATUS_FLOW,
    Customer,
    Product,
    SalesOrder,
    SalesOrderItem,
)


@pytest.fixture(scope="function")
def test_engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture(scope="function")
def test_session(test_engine):
    Base.metadata.create_all(test_engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_order(db, status="quote"):
    customer = Customer(customer_name="测试客户A")
    db.add(customer)
    db.commit()
    db.refresh(customer)
    order = SalesOrder(
        order_no="SO-2026-0001",
        customer_id=customer.id,
        customer_name=customer.customer_name,
        status=status,
        quote_date=date(2026, 8, 1),
        total_amount=1000.0,
        paid_amount=0,
    )
    product = Product(name="产品X", price=100.0, unit="个", is_active=1)
    db.add(product)
    db.commit()
    db.refresh(product)
    item = SalesOrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        quantity=10,
        unit="个",
        unit_price=100.0,
        amount=1000.0,
    )
    order.items.append(item)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order, item


class TestSalesOrderStatusFlow:
    def test_status_flow_order(self):
        """状态机顺序必须是 quote->confirmed->delivered->invoiced->paid。"""
        assert SALES_ORDER_STATUS_FLOW == [
            "quote",
            "confirmed",
            "delivered",
            "invoiced",
            "paid",
        ]

    def test_full_closed_loop(self, test_session):
        """建单->确认->发货->开票->收款 全闭环推进。"""
        order, _ = _make_order(test_session, status="quote")
        assert order.status == "quote"

        order.advance("confirmed")
        order.confirm_date = date(2026, 8, 2)
        test_session.commit()
        test_session.refresh(order)
        assert order.status == "confirmed"

        order.advance("delivered")
        test_session.commit()
        test_session.refresh(order)
        assert order.status == "delivered"

        order.advance("invoiced")
        test_session.commit()
        test_session.refresh(order)
        assert order.status == "invoiced"

        order.advance("paid")
        order.paid_amount = order.total_amount
        test_session.commit()
        test_session.refresh(order)
        assert order.status == "paid"
        assert order.paid_amount == order.total_amount

    def test_reject_illegal_status(self, test_session):
        """未知状态被拒绝。"""
        order, _ = _make_order(test_session, status="quote")
        with pytest.raises(ValueError):
            order.advance("not_a_status")

    def test_reject_rollback(self, test_session):
        """状态不允许回退（paid 不能回到 quote）。"""
        order, _ = _make_order(test_session, status="paid")
        with pytest.raises(ValueError):
            order.advance("quote")

    def test_advance_same_status_noop(self, test_session):
        """推进到当前状态为幂等（不报错）。"""
        order, _ = _make_order(test_session, status="confirmed")
        order.advance("confirmed")
        assert order.status == "confirmed"


class TestSalesOrderItem:
    def test_item_quantities(self, test_session):
        """明细行数量/金额/交付/开票数量可写入。"""
        _order, item = _make_order(test_session)
        item.delivered_quantity = 8
        item.invoiced_quantity = 6
        test_session.commit()
        test_session.refresh(item)
        assert item.delivered_quantity == 8
        assert item.invoiced_quantity == 6
        assert item.amount == 1000.0

    def test_order_items_cascade(self, test_session):
        """删除订单级联删除明细。"""
        order, _ = _make_order(test_session)
        order_id = order.id
        test_session.delete(order)
        test_session.commit()
        remaining = test_session.query(SalesOrderItem).filter_by(order_id=order_id).count()
        assert remaining == 0


class TestSalesOrderToDict:
    def test_to_dict(self, test_session):
        """序列化为 dict 供 Agent 响应使用。"""
        order, item = _make_order(test_session)
        d = order.to_dict()
        assert d["order_no"] == "SO-2026-0001"
        assert d["status"] == "quote"
        assert d["total_amount"] == 1000.0
        assert d["paid_amount"] == 0.0
        item_d = item.to_dict()
        assert item_d["quantity"] == 10
        assert item_d["amount"] == 1000.0