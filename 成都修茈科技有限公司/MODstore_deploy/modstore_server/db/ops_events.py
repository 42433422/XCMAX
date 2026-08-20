"""站内通知、风控与事务型 outbox。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column("type", String(32), nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    data_json = Column(Text, default="{}")
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    ip = Column(String(64), default="", index=True)
    event_type = Column(String(64), nullable=False, index=True)
    provider = Column(String(64), default="")
    model = Column(String(256), default="")
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class OutboxEvent(Base):
    __tablename__ = "event_outbox"
    __table_args__ = (UniqueConstraint("event_id", name="uq_event_outbox_event_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(128), nullable=False, index=True)
    event_name = Column(String(64), nullable=False, index=True)
    event_version = Column(Integer, default=1, nullable=False)
    aggregate_id = Column(String(128), default="", index=True)
    idempotency_key = Column(String(192), default="", index=True)
    producer = Column(String(64), default="modstore-python")
    payload_json = Column(Text, default="{}")
    status = Column(String(16), default="pending", index=True)
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    dispatched_at = Column(DateTime, nullable=True)


class OutboxDeadLetter(Base):
    __tablename__ = "event_outbox_dlq"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_outbox_id = Column(Integer, nullable=True, index=True)
    event_id = Column(String(128), nullable=False, index=True)
    event_name = Column(String(64), nullable=False, index=True)
    event_version = Column(Integer, default=1, nullable=False)
    aggregate_id = Column(String(128), default="", index=True)
    idempotency_key = Column(String(192), default="", index=True)
    producer = Column(String(64), default="modstore-python")
    payload_json = Column(Text, default="{}")
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    moved_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    # Resolution is append-only operational evidence.  Rows are retained even
    # when replay is unsafe (payment/refund etc.) so fault debt can be closed
    # without deleting the audit trail.
    resolution_status = Column(String(32), default="", index=True)
    resolution_action = Column(String(32), default="")
    resolution_note = Column(Text, default="")
    resolved_at = Column(DateTime, nullable=True, index=True)
    last_reconciled_at = Column(DateTime, nullable=True)
    replay_outbox_id = Column(Integer, nullable=True)
