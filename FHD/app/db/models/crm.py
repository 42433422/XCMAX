from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin, TimestampMixin

# 地址类型（Odoo res.partner 收货/发票地址吸收）
ADDRESS_TYPES = {"invoice", "delivery"}


class CustomerAddress(IntegerPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """客户地址（Odoo res.partner 的发票 invoice / 送货 delivery 地址吸收）。"""

    __tablename__ = "customer_addresses"

    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True
    )
    # 地址类型：invoice(发票) / delivery(送货)
    address_type: Mapped[str] = mapped_column(String(20), default="delivery", index=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    # 默认地址标志：0/1
    is_default: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "address_type": self.address_type,
            "contact_person": self.contact_person or "",
            "phone": self.phone or "",
            "address": self.address or "",
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
