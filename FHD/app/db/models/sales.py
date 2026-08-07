from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 销售订单状态机（Sales-to-Payment 闭环）
# quote(报价) -> confirmed(确认) -> delivered(发货) -> invoiced(开票) -> paid(收款)
SALES_ORDER_STATUS_FLOW = ["quote", "confirmed", "delivered", "invoiced", "paid"]

SALES_ITEM_STATUS_FLOW = ["pending", "delivered", "invoiced", "paid"]


class SalesOrder(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """销售订单（Odoo sale.order 吸收：报价->确认->发货->开票->收款状态机闭环）。"""

    __tablename__ = "sales_orders"

    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("customers.id"), nullable=True, index=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(20), default="quote", index=True)
    quote_date: Mapped[Optional[date]] = mapped_column(Date)
    confirm_date: Mapped[Optional[date]] = mapped_column(Date)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    paid_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    remark: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[list[SalesOrderItem]] = relationship(
        "SalesOrderItem", back_populates="sales_order", cascade="all, delete-orphan", lazy="selectin"
    )

    def advance(self, new_status: str) -> None:
        """推进销售订单状态机；非法跳转会抛 ValueError（供 Agent 工作流调用）。"""
        if new_status == self.status:
            return
        flow = SALES_ORDER_STATUS_FLOW
        if new_status not in flow:
            raise ValueError(f"非法销售订单状态: {new_status}")
        if self.status in flow and flow.index(new_status) < flow.index(self.status):
            raise ValueError(
                f"销售订单状态不允许回退: {self.status} -> {new_status}"
            )
        self.status = new_status

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_no": self.order_no,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "status": self.status,
            "quote_date": self.quote_date.isoformat() if self.quote_date else None,
            "confirm_date": self.confirm_date.isoformat() if self.confirm_date else None,
            "total_amount": float(self.total_amount) if self.total_amount is not None else 0.0,
            "paid_amount": float(self.paid_amount) if self.paid_amount is not None else 0.0,
            "currency": self.currency,
            "remark": self.remark,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SalesOrderItem(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    """销售订单明细（Odoo sale.order.line 吸收）。"""

    __tablename__ = "sales_order_items"

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
    delivered_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    invoiced_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sales_order: Mapped[Optional[SalesOrder]] = relationship(
        "SalesOrder", back_populates="items"
    )

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
            "delivered_quantity": (
                float(self.delivered_quantity) if self.delivered_quantity is not None else 0.0
            ),
            "invoiced_quantity": (
                float(self.invoiced_quantity) if self.invoiced_quantity is not None else 0.0
            ),
            "status": self.status,
        }


from app.db.models.customer import Customer  # noqa: E402
from app.db.models.product import Product  # noqa: E402