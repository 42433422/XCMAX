from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class Product(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_unit", "unit"),
        Index("ix_products_model_number", "model_number"),
        # UOM 换算/补货字段的 DB 级约束（字段可空，用 COALESCE 兜底默认值）
        CheckConstraint("COALESCE(uom_factor, 1) > 0", name="ck_products_uom_factor_positive"),
        CheckConstraint("COALESCE(min_stock, 0) >= 0", name="ck_products_min_stock_nonnegative"),
        CheckConstraint("COALESCE(max_stock, 0) >= 0", name="ck_products_max_stock_nonnegative"),
        CheckConstraint(
            "COALESCE(min_stock, 0) <= COALESCE(max_stock, 0)",
            name="ck_products_min_stock_le_max_stock",
        ),
    )
    model_number: Mapped[Optional[str]] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, nullable=False)
    specification: Mapped[Optional[str]] = mapped_column(String)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), default=0.0)
    quantity: Mapped[Optional[int]] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String)
    category: Mapped[Optional[str]] = mapped_column(String)
    brand: Mapped[Optional[str]] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String, default="个")
    # 基准计量单位（Odoo 吸收）：指向 uom_units 主记录（base 单位 factor=1）
    base_uom_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("uom_units.id"), nullable=True, index=True
    )
    # UOM（单位换算，Odoo 吸收）：category 表示量纲（如 weight/count/volume），
    # factor 为相对基准单位的换算系数（base 单位 factor=1，换算后数量/金额需一致）
    uom_category: Mapped[Optional[str]] = mapped_column(String, default="unit", index=True)
    uom_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), default=Decimal("1"))
    # 补货规则（Odoo reordering rules 吸收）：低库存预警与建议量依据
    min_stock: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    max_stock: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    # tenant_id 由 TenantScopedMixin 提供（多租户数据隔离作用域）


class UomCategory(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """单位类别（量纲）：同一类别内的单位可互相换算，跨类别不可直接换算。"""

    __tablename__ = "uom_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_uom_categories_tenant_code"),)

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1)

    units: Mapped[list[UomUnit]] = relationship("UomUnit", back_populates="category")


class UomUnit(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """单位：属于某类别，``factor`` 为相对该类别基准单位(base, factor=1)的换算系数。"""

    __tablename__ = "uom_units"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "category_id",
            "code",
            name="uq_uom_units_tenant_category_code",
        ),
        CheckConstraint("factor > 0", name="ck_uom_units_factor_positive"),
        CheckConstraint("is_reference IN (0, 1)", name="ck_uom_units_is_reference_bool"),
    )

    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("uom_categories.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 相对该类基准单位的换算系数（基准单位 factor=1；目标单位数量 = 基准数量 / factor）
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))
    # 是否为基准单位（0=普通单位 / 1=基准单位；每类别至多一个基准单位）
    is_reference: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[int] = mapped_column(Integer, default=1)

    category: Mapped[UomCategory] = relationship("UomCategory", back_populates="units")
