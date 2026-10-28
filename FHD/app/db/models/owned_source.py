"""Real mixed-source mappings, isolated from host Base and host startup DDL.

Product FK targets the existing canonical table, not a placeholder. Enrollment
creates an explicit full FK closure; importing these models never creates tables.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin
from app.db.models.product import Product


class OwnedSourceBase(DeclarativeBase):
    pass


class ProductPriceHistory(
    IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, OwnedSourceBase
):
    __tablename__ = "product_price_history"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "source_key", name="uq_product_price_source"),
        Index("ix_product_price_period", "tenant_id", "product_id", "period_start"),
        CheckConstraint("price >= 0", name="ck_product_price_nonnegative"),
        CheckConstraint(
            "(period_start IS NULL AND period_end IS NULL) OR "
            "(period_start IS NOT NULL AND period_end IS NOT NULL AND period_end > period_start)",
            name="ck_product_price_period",
        ),
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Product.__table__.c.id), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[Optional[date]] = mapped_column(Date)
    period_end: Mapped[Optional[date]] = mapped_column(Date)
    period_label: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)


class EtlPriceDimension(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, OwnedSourceBase):
    __tablename__ = "etl_price_dimensions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", name="uq_etl_price_dimensions_product"),
    )

    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(Product.__table__.c.id), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_id: Mapped[int] = mapped_column(Integer, nullable=False)
