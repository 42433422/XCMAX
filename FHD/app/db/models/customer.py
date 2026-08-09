from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin


class Customer(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "customers"
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(100))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    contact_address: Mapped[Optional[str]] = mapped_column(String(500))
    # 信用额度（Odoo 客户信用控制吸收）
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    credit_used: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    is_credit_limited: Mapped[int] = mapped_column(default=0)
    # tenant_id 由 TenantScopedMixin 提供（多租户数据隔离作用域）
