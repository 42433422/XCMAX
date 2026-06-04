"""客户交付签收（PostgreSQL，与 CRM SQLite 商机 id 逻辑关联）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CsDeliverySignoff(Base):
    __tablename__ = "cs_delivery_signoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    market_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    signed_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    signed_role: Mapped[str] = mapped_column(String(32), nullable=False, default="customer")
    attachment_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_cs_delivery_signoffs_opp_status", "opportunity_id", "status"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "market_user_id": self.market_user_id,
            "status": self.status,
            "signed_by": self.signed_by,
            "signed_role": self.signed_role,
            "attachment_url": self.attachment_url,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
        }
