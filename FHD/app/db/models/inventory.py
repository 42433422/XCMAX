from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TenantScopedMixin


class Warehouse(TenantScopedMixin, Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(Text)
    manager: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    locations: Mapped[list[StorageLocation]] = relationship(
        "StorageLocation", back_populates="warehouse"
    )
    inventory_ledgers: Mapped[list[InventoryLedger]] = relationship(
        "InventoryLedger", back_populates="warehouse"
    )


class StorageLocation(TenantScopedMixin, Base):
    __tablename__ = "storage_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    max_capacity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    current_capacity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    warehouse: Mapped[Optional[Warehouse]] = relationship("Warehouse", back_populates="locations")
    inventory_ledgers: Mapped[list[InventoryLedger]] = relationship(
        "InventoryLedger", back_populates="location"
    )


class InventoryLedger(TenantScopedMixin, Base):
    __tablename__ = "inventory_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("storage_locations.id"))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    available_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    reserved_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    unit: Mapped[str] = mapped_column(String(20), default="个")
    in_date: Mapped[Optional[date]] = mapped_column(Date)
    expire_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    product: Mapped[Optional[Product]] = relationship("Product")
    warehouse: Mapped[Optional[Warehouse]] = relationship(
        "Warehouse", back_populates="inventory_ledgers"
    )
    location: Mapped[Optional[StorageLocation]] = relationship(
        "StorageLocation", back_populates="inventory_ledgers"
    )
    transactions: Mapped[list[InventoryTransaction]] = relationship(
        "InventoryTransaction", back_populates="ledger"
    )


class InventoryTransaction(TenantScopedMixin, Base):
    __tablename__ = "inventory_transactions"

    __table_args__ = (
        CheckConstraint(
            "COALESCE(ordered_quantity, 0) >= 0",
            name="ck_inventory_transactions_ordered_quantity_nonnegative",
        ),
        CheckConstraint(
            "COALESCE(delivered_quantity, 0) >= 0",
            name="ck_inventory_transactions_delivered_quantity_nonnegative",
        ),
        CheckConstraint(
            "COALESCE(delivered_quantity, 0) <= COALESCE(ordered_quantity, 0)",
            name="ck_inventory_transactions_delivered_not_exceed_ordered",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ledger_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("inventory_ledger.id"))
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("storage_locations.id"))
    batch_no: Mapped[Optional[str]] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    before_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    after_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    reference_type: Mapped[Optional[str]] = mapped_column(String(50))
    reference_id: Mapped[Optional[int]] = mapped_column(Integer)
    # 履行维度（stock moves 复用本表，不新建 move 表）：按单/按明细分派数量
    ordered_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    delivered_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=0)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_orders.id"), nullable=True, index=True
    )
    sales_order_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order_items.id"), nullable=True, index=True
    )
    transaction_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    operator: Mapped[Optional[str]] = mapped_column(String(50))
    remark: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    ledger: Mapped[Optional[InventoryLedger]] = relationship(
        "InventoryLedger", back_populates="transactions"
    )
    product: Mapped[Optional[Product]] = relationship("Product")
    warehouse: Mapped[Optional[Warehouse]] = relationship("Warehouse")
    location: Mapped[Optional[StorageLocation]] = relationship("StorageLocation")


from app.db.models.product import Product  # noqa: E402
