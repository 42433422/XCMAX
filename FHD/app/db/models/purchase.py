from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.db_base import Base
from app.db.mixins import TenantScopedMixin


class Supplier(TenantScopedMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index(
            "uq_supplier_tenant_live_name",
            "tenant_id",
            text("lower(trim(name))"),
            unique=True,
            sqlite_where=text("tenant_id IS NOT NULL AND coalesce(status, '') <> 'deleted'"),
            postgresql_where=text("tenant_id IS NOT NULL AND coalesce(status, '') <> 'deleted'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(50))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    contact_email: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(50))
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    rating: Mapped[int] = mapped_column(Integer, default=3)
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(
        "PurchaseOrder", back_populates="supplier"
    )


class PurchaseOrder(TenantScopedMixin, Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=False)
    warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("warehouses.id"))
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    paid_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    approver: Mapped[Optional[str]] = mapped_column(String(50))
    approve_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    supplier: Mapped[Optional[Supplier]] = relationship(
        "Supplier", back_populates="purchase_orders"
    )
    items: Mapped[list[PurchaseOrderItem]] = relationship(
        "PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan"
    )
    warehouse: Mapped[Optional[Warehouse]] = relationship("Warehouse")


class PurchaseOrderItem(TenantScopedMixin, Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    product_name: Mapped[Optional[str]] = mapped_column(String(200))
    specification: Mapped[Optional[str]] = mapped_column(String(200))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="个")
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    received_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    invoiced_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    purchase_order: Mapped[Optional[PurchaseOrder]] = relationship(
        "PurchaseOrder", back_populates="items"
    )
    product: Mapped[Optional[Product]] = relationship("Product")


class PurchaseInbound(TenantScopedMixin, Base):
    __tablename__ = "purchase_inbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inbound_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("purchase_orders.id"))
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    inbound_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    handler: Mapped[Optional[str]] = mapped_column(String(50))
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    supplier: Mapped[Optional[Supplier]] = relationship("Supplier")
    warehouse: Mapped[Optional[Warehouse]] = relationship("Warehouse")
    purchase_order: Mapped[Optional[PurchaseOrder]] = relationship("PurchaseOrder")
    items: Mapped[list[PurchaseInboundItem]] = relationship(
        "PurchaseInboundItem", back_populates="inbound", cascade="all, delete-orphan"
    )


class PurchaseInboundItem(TenantScopedMixin, Base):
    __tablename__ = "purchase_inbound_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inbound_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_inbounds.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    order_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("purchase_order_items.id")
    )
    product_name: Mapped[Optional[str]] = mapped_column(String(200))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="个")
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=0)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("storage_locations.id"))
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    inbound: Mapped[Optional[PurchaseInbound]] = relationship(
        "PurchaseInbound", back_populates="items"
    )
    product: Mapped[Optional[Product]] = relationship("Product")
    order_item: Mapped[Optional[PurchaseOrderItem]] = relationship("PurchaseOrderItem")
    location: Mapped[Optional[StorageLocation]] = relationship("StorageLocation")


class PurchaseReturn(TenantScopedMixin, Base):
    """A posted supplier return tied to one original purchase receipt."""

    __tablename__ = "purchase_returns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "return_no", name="uq_purchase_returns_tenant_no"),
        UniqueConstraint(
            "tenant_id", "approval_request_id",
            name="uq_purchase_returns_approved_request",
        ),
        CheckConstraint("total_amount >= 0", name="ck_purchase_return_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    return_no: Mapped[str] = mapped_column(String(50), nullable=False)
    approval_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("approval_requests.id"), nullable=False
    )
    inbound_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_inbounds.id"), nullable=False
    )
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("journal_entries.id")
    )
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    items: Mapped[list[PurchaseReturnItem]] = relationship(
        "PurchaseReturnItem", back_populates="purchase_return",
        cascade="all, delete-orphan",
    )


class PurchaseReturnItem(TenantScopedMixin, Base):
    __tablename__ = "purchase_return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_return_item_qty_positive"),
        CheckConstraint("amount >= 0", name="ck_purchase_return_item_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    return_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_returns.id"), nullable=False
    )
    inbound_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_inbound_items.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    location_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("storage_locations.id")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    purchase_return: Mapped[PurchaseReturn] = relationship(
        "PurchaseReturn", back_populates="items"
    )


from app.db.models.inventory import StorageLocation, Warehouse
from app.db.models.product import Product
