from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db import Base


class ModelPaymentOrder(Base):
    __tablename__ = "model_payment_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    out_trade_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_yuan: Mapped[str] = mapped_column(String(32), nullable=False, default="0.00")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_payment", index=True
    )
    trade_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    market_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    notify_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_notify_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_notify: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (Index("ix_model_payment_orders_plan_status", "plan_id", "status"),)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "out_trade_no": self.out_trade_no,
            "plan_id": self.plan_id,
            "amount_cents": self.amount_cents,
            "amount_yuan": self.amount_yuan,
            "status": self.status,
            "trade_no": self.trade_no,
            "market_user_id": self.market_user_id,
            "notify_count": self.notify_count,
            "last_notify_at": self.last_notify_at.isoformat() if self.last_notify_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ModelPaymentEntitlement(Base):
    __tablename__ = "model_payment_entitlements"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    purchase_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    last_out_trade_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_trade_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "purchase_count": self.purchase_count,
            "first_paid_at": self.first_paid_at.isoformat() if self.first_paid_at else None,
            "last_paid_at": self.last_paid_at.isoformat() if self.last_paid_at else None,
            "last_out_trade_no": self.last_out_trade_no,
            "last_trade_no": self.last_trade_no,
        }
