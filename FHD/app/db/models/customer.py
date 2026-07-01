from __future__ import annotations

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class Customer(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "customers"
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(100))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    contact_address: Mapped[Optional[str]] = mapped_column(String(500))
    # tenant_id 由 TenantScopedMixin 提供（多租户数据隔离作用域）
