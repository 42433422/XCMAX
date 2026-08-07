"""MRP 生产制造模型（Odoo mrp.bom / mrp.production 吸收）。

Task 3（upgrade-erp-modules-odoo18）：
- Bom 物料清单（成品 + 原料展开）
- BomLine BOM 明细行（每单位成品所需原料量）
- ManufacturingOrder 生产工单
- ManufacturingOrderLine 工单用料行（计划领料 / 已领料）
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 生产工单状态
ORDER_STATUSES = {"draft", "confirmed", "in_progress", "done", "cancelled"}

# BOM 状态
BOM_STATUSES = {"draft", "active", "inactive"}


class Bom(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """物料清单（BOM）：成品及其构成原料的展开关系。"""

    __tablename__ = "boms"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)

    lines: Mapped[list[BomLine]] = relationship(
        "BomLine", back_populates="bom", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "status": self.status,
            "lines": [line.to_dict() for line in self.lines],
        }


class BomLine(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    """BOM 明细行：生产一单位成品所需某原料的数量。"""

    __tablename__ = "bom_lines"

    bom_id: Mapped[int] = mapped_column(Integer, ForeignKey("boms.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(20), default="个")

    bom: Mapped[Optional[Bom]] = relationship("Bom", back_populates="lines")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bom_id": self.bom_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": float(self.quantity) if self.quantity is not None else 0.0,
            "unit": self.unit,
        }


class ManufacturingOrder(
    IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base
):
    """生产工单（Odoo mrp.production 吸收）。"""

    __tablename__ = "manufacturing_orders"

    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    bom_id: Mapped[int] = mapped_column(Integer, ForeignKey("boms.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("warehouses.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)

    lines: Mapped[list[ManufacturingOrderLine]] = relationship(
        "ManufacturingOrderLine",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_no": self.order_no,
            "bom_id": self.bom_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "warehouse_id": self.warehouse_id,
            "status": self.status,
            "lines": [line.to_dict() for line in self.lines],
        }


class ManufacturingOrderLine(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    """生产工单用料行：计划领料量 / 已领料量。"""

    __tablename__ = "manufacturing_order_lines"

    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("manufacturing_orders.id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    consumed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    unit: Mapped[str] = mapped_column(String(20), default="个")

    order: Mapped[Optional[ManufacturingOrder]] = relationship(
        "ManufacturingOrder", back_populates="lines"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "order_id": self.order_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": float(self.quantity) if self.quantity is not None else 0.0,
            "consumed_quantity": (
                float(self.consumed_quantity) if self.consumed_quantity is not None else 0.0
            ),
            "unit": self.unit,
        }