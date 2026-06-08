"""AI 业务证据表：发货单审单事件、合同到期推送记录。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ShipmentAuditEvent(Base):
    __tablename__ = "shipment_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    shipment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(512))
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="shipment")


class ContractExpiryNotification(Base):
    __tablename__ = "contract_expiry_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    end_date: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    push_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    push_channel: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
