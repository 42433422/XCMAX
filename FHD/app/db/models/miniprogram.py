"""微信小程序 CRM 相关 ORM 模型（与 alembic xcagi_v5_miniprogram 对齐）。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User


class MpCart(Base):
    __tablename__ = "mp_carts"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_mp_cart_user_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    selected: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MpOrder(Base):
    __tablename__ = "mp_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    pay_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    pay_status: Mapped[Optional[str]] = mapped_column(String(20), default="unpaid")
    pay_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivery_name: Mapped[Optional[str]] = mapped_column(String(64))
    delivery_phone: Mapped[Optional[str]] = mapped_column(String(20))
    delivery_address: Mapped[Optional[str]] = mapped_column(Text)
    delivery_province: Mapped[Optional[str]] = mapped_column(String(32))
    delivery_city: Mapped[Optional[str]] = mapped_column(String(32))
    delivery_district: Mapped[Optional[str]] = mapped_column(String(32))
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", backref="mp_orders")
    items: Mapped[list[MpOrderItem]] = relationship(
        "MpOrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class MpOrderItem(Base):
    __tablename__ = "mp_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mp_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    product_sku: Mapped[Optional[str]] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    remark: Mapped[Optional[str]] = mapped_column(Text)

    order: Mapped[MpOrder] = relationship("MpOrder", back_populates="items")


class MpAddress(Base):
    __tablename__ = "mp_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    province: Mapped[str] = mapped_column(String(32), nullable=False)
    city: Mapped[str] = mapped_column(String(32), nullable=False)
    district: Mapped[str] = mapped_column(String(32), nullable=False)
    detail_address: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MpBrowseHistory(Base):
    __tablename__ = "mp_browse_history"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_mp_browse_user_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MpFavorite(Base):
    __tablename__ = "mp_favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_mp_fav_user_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MpNotification(Base):
    __tablename__ = "mp_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[str]] = mapped_column(String(32), default="system")
    is_read: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    related_type: Mapped[Optional[str]] = mapped_column(String(32))
    related_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MpFeedback(Base):
    __tablename__ = "mp_feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    images: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(20), default="pending")
    reply: Mapped[Optional[str]] = mapped_column(Text)
    replied_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"))
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        backref="mp_feedbacks",
        overlaps="user",
    )


__all__ = [
    "MpAddress",
    "MpBrowseHistory",
    "MpCart",
    "MpFavorite",
    "MpFeedback",
    "MpNotification",
    "MpOrder",
    "MpOrderItem",
]
