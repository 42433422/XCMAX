"""Explicit customer-product association, independent of measurement units."""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class CustomerProductLink(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "customer_product_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "purchase_unit_id", "product_id", name="uq_customer_product_link"
        ),
    )
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    purchase_unit_id: Mapped[int] = mapped_column(ForeignKey("purchase_units.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
