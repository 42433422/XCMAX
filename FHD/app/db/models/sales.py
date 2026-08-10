from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 销售订单正交维度状态（Odoo 派生，替代单一线性状态机）
# 商业单状态（commercial order state）：draft/quote/sent/confirmed/cancel
SALES_ORDER_STATE_FLOW = ["draft", "quote", "sent", "confirmed", "cancel"]

# 开票状态（invoice status）：独立维度
INVOICE_STATUS_VALUES = ["not_invoiced", "invoiced", "invoiced_partial", "credit_note"]

# 收款状态（payment state）：独立维度
PAYMENT_STATE_VALUES = ["unpaid", "partial", "paid", "refunded"]

# 兼容旧单线程状态机（仅保留给遗留读取，不再驱动业务副作用）
SALES_ORDER_STATUS_FLOW = ["quote", "confirmed", "delivered", "invoiced", "paid"]

SALES_ITEM_STATUS_FLOW = ["pending", "delivered", "invoiced", "paid"]

# 履行派生口径（由四类数量计算，不读取金额）
FULFILLMENT_PARTIAL = "partial"
FULFILLMENT_BACKORDER = "backorder"
FULFILLMENT_RETURN = "return"


class SalesOrder(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """销售订单（Odoo sale.order 吸收）。

    采用正交维度建模：
    - ``state``：商业单状态（draft/quote/sent/confirmed/cancel）
    - ``invoice_status``：开票状态（独立）
    - ``payment_state``：收款状态（独立）
    - ``fulfillment``：由各明细的 ordered/reserved/delivered/returned 数量派生，不读金额
    """

    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_no", name="uq_sales_orders_tenant_order_no"),
        CheckConstraint(
            "state IN ('draft','quote','sent','confirmed','cancel')",
            name="ck_sales_orders_state_valid",
        ),
        CheckConstraint(
            "invoice_status IN ('not_invoiced','invoiced','invoiced_partial','credit_note')",
            name="ck_sales_orders_invoice_status_valid",
        ),
        CheckConstraint(
            "payment_state IN ('unpaid','partial','paid','refunded')",
            name="ck_sales_orders_payment_state_valid",
        ),
        CheckConstraint(
            "COALESCE(total_amount, 0) >= 0",
            name="ck_sales_orders_total_amount_non_negative",
        ),
        CheckConstraint(
            "COALESCE(paid_amount, 0) >= 0",
            name="ck_sales_orders_paid_amount_non_negative",
        ),
    )

    order_no: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("customers.id"), nullable=True, index=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(200), index=True)

    # 商业单状态（正交维度）
    state: Mapped[str] = mapped_column(String(20), default="quote", index=True)
    # 兼容遗留线性状态（quote/confirmed/delivered/invoiced/paid）；不驱动业务副作用
    status: Mapped[str] = mapped_column(String(20), default="quote", index=True)
    # 开票 / 收款 独立维度
    invoice_status: Mapped[str] = mapped_column(String(20), default="not_invoiced", index=True)
    payment_state: Mapped[str] = mapped_column(String(20), default="unpaid", index=True)

    quote_date: Mapped[Optional[date]] = mapped_column(Date)
    sent_date: Mapped[Optional[date]] = mapped_column(Date)
    confirm_date: Mapped[Optional[date]] = mapped_column(Date)
    cancel_date: Mapped[Optional[date]] = mapped_column(Date)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    paid_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    remark: Mapped[Optional[str]] = mapped_column(Text)

    # backorder / return 关联：本单是哪个订单的补货(backorder)或退货(return)
    backorder_of_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_orders.id"), nullable=True, index=True
    )
    return_of_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_orders.id"), nullable=True, index=True
    )

    items: Mapped[list[SalesOrderItem]] = relationship(
        "SalesOrderItem",
        back_populates="sales_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # backorder / return 子单关系
    backorders: Mapped[list[SalesOrder]] = relationship(
        "SalesOrder",
        back_populates="backorder_of",
        foreign_keys="SalesOrder.backorder_of_id",
    )
    backorder_of: Mapped[Optional[SalesOrder]] = relationship(
        "SalesOrder",
        back_populates="backorders",
        foreign_keys="SalesOrder.backorder_of_id",
        remote_side="SalesOrder.id",
    )
    returns: Mapped[list[SalesOrder]] = relationship(
        "SalesOrder",
        back_populates="return_of",
        foreign_keys="SalesOrder.return_of_id",
    )
    return_of: Mapped[Optional[SalesOrder]] = relationship(
        "SalesOrder",
        back_populates="returns",
        foreign_keys="SalesOrder.return_of_id",
        remote_side="SalesOrder.id",
    )

    def advance(self, new_status: str) -> None:
        """兼容遗留线性状态机推进；仅供遗留读取，新逻辑请操作 ``state``。"""
        if new_status == self.status:
            return
        flow = SALES_ORDER_STATUS_FLOW
        if new_status not in flow:
            raise ValueError(f"非法销售订单状态: {new_status}")
        if self.status in flow and flow.index(new_status) < flow.index(self.status):
            raise ValueError(f"销售订单状态不允许回退: {self.status} -> {new_status}")
        self.status = new_status

    def set_state(self, new_state: str) -> None:
        """推进商业单状态（正交维度）；回退被拒。"""
        if new_state == self.state:
            return
        if new_state not in SALES_ORDER_STATE_FLOW:
            raise ValueError(f"非法销售订单状态: {new_state}")
        allowed = {
            "draft": {"quote", "cancel"},
            "quote": {"sent", "confirmed", "cancel"},
            "sent": {"confirmed", "cancel"},
            "confirmed": {"cancel"},
            "cancel": set(),
        }
        if new_state not in allowed.get(self.state, set()):
            raise ValueError(f"销售订单状态不允许从 {self.state} 到 {new_state}")
        self.state = new_state

    def fulfillment_state(self) -> str:
        """履行派生口径：仅由四类数量计算，不读取金额。"""
        if not self.items:
            return "unfulfilled"
        zero = Decimal("0")
        total_ordered = sum((i.ordered_quantity or zero) for i in self.items)
        total_delivered = sum((i.delivered_quantity or zero) for i in self.items)
        total_returned = sum((i.returned_quantity or zero) for i in self.items)
        if total_delivered <= 0:
            return "unfulfilled"
        if total_returned >= total_ordered > 0:
            return FULFILLMENT_RETURN
        if total_delivered < total_ordered:
            return FULFILLMENT_PARTIAL
        return "delivered"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_no": self.order_no,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "state": self.state,
            "status": self.status,
            "invoice_status": self.invoice_status,
            "payment_state": self.payment_state,
            "fulfillment": self.fulfillment_state(),
            "quote_date": self.quote_date.isoformat() if self.quote_date else None,
            "sent_date": self.sent_date.isoformat() if self.sent_date else None,
            "confirm_date": self.confirm_date.isoformat() if self.confirm_date else None,
            "cancel_date": self.cancel_date.isoformat() if self.cancel_date else None,
            "total_amount": float(self.total_amount) if self.total_amount is not None else 0.0,
            "paid_amount": float(self.paid_amount) if self.paid_amount is not None else 0.0,
            "currency": self.currency,
            "remark": self.remark,
            "backorder_of_id": self.backorder_of_id,
            "return_of_id": self.return_of_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SalesOrderItem(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    """销售订单明细（Odoo sale.order.line 吸收）。

    履行维度由 ordered / reserved / delivered / returned 四类数量派生。
    """

    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint(
            "COALESCE(quantity, 0) >= 0",
            name="ck_sales_order_items_quantity_non_negative",
        ),
        CheckConstraint(
            "COALESCE(unit_price, 0) >= 0",
            name="ck_sales_order_items_unit_price_non_negative",
        ),
        CheckConstraint(
            "COALESCE(amount, 0) >= 0",
            name="ck_sales_order_items_amount_non_negative",
        ),
        CheckConstraint(
            "COALESCE(ordered_quantity, 0) >= 0",
            name="ck_sales_order_items_ordered_non_negative",
        ),
        CheckConstraint(
            "COALESCE(reserved_quantity, 0) >= 0",
            name="ck_sales_order_items_reserved_non_negative",
        ),
        CheckConstraint(
            "COALESCE(delivered_quantity, 0) >= 0",
            name="ck_sales_order_items_delivered_non_negative",
        ),
        CheckConstraint(
            "COALESCE(returned_quantity, 0) >= 0",
            name="ck_sales_order_items_returned_non_negative",
        ),
        CheckConstraint(
            "COALESCE(invoiced_quantity, 0) >= 0",
            name="ck_sales_order_items_invoiced_non_negative",
        ),
        CheckConstraint(
            "COALESCE(reserved_quantity, 0) <= COALESCE(ordered_quantity, 0)",
            name="ck_sales_order_items_reserved_le_ordered",
        ),
        CheckConstraint(
            "COALESCE(delivered_quantity, 0) <= COALESCE(ordered_quantity, 0)",
            name="ck_sales_order_items_delivered_le_ordered",
        ),
        CheckConstraint(
            "COALESCE(returned_quantity, 0) <= COALESCE(delivered_quantity, 0)",
            name="ck_sales_order_items_returned_le_delivered",
        ),
    )

    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id"), nullable=False, index=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True, index=True
    )
    product_name: Mapped[Optional[str]] = mapped_column(String(200))
    specification: Mapped[Optional[str]] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="个")
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)

    # 履行四类数量
    ordered_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    reserved_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    delivered_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    returned_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    invoiced_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)

    status: Mapped[str] = mapped_column(String(20), default="pending")
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sales_order: Mapped[Optional[SalesOrder]] = relationship("SalesOrder", back_populates="items")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "specification": self.specification,
            "quantity": float(self.quantity),
            "unit": self.unit,
            "unit_price": float(self.unit_price) if self.unit_price is not None else 0.0,
            "amount": float(self.amount) if self.amount is not None else 0.0,
            "ordered_quantity": (
                float(self.ordered_quantity) if self.ordered_quantity is not None else 0.0
            ),
            "reserved_quantity": (
                float(self.reserved_quantity) if self.reserved_quantity is not None else 0.0
            ),
            "delivered_quantity": (
                float(self.delivered_quantity) if self.delivered_quantity is not None else 0.0
            ),
            "returned_quantity": (
                float(self.returned_quantity) if self.returned_quantity is not None else 0.0
            ),
            "invoiced_quantity": (
                float(self.invoiced_quantity) if self.invoiced_quantity is not None else 0.0
            ),
            "status": self.status,
        }
