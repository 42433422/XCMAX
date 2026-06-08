"""开发者 PAT、出站 Webhook 订阅与投递审计。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from modstore_server.db.base import Base


class DeveloperToken(Base):
    __tablename__ = "developer_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_developer_token_hash"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False, default="")
    token_prefix = Column(String(16), nullable=False, default="")
    token_hash = Column(String(128), nullable=False, index=True)
    scopes_json = Column(Text, default="[]")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DeveloperKeyExportEvent(Base):
    __tablename__ = "developer_key_export_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    client_ip = Column(String(64), nullable=False, default="")
    user_agent = Column(String(512), nullable=False, default="")
    action = Column(String(64), nullable=False, default="")
    token_ids_json = Column(Text, nullable=False, default="[]")
    token_count = Column(Integer, nullable=False, default=0)
    success = Column(Boolean, nullable=False, default=False)
    detail = Column(String(512), nullable=False, default="")
    algorithm = Column(String(64), nullable=False, default="")


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False, default="")
    description = Column(Text, default="")
    target_url = Column(String(1024), nullable=False)
    secret_encrypted = Column(Text, nullable=False, default="")
    enabled_events_json = Column(Text, default='["*"]')
    is_active = Column(Boolean, default=True, index=True)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    last_delivery_at = Column(DateTime, nullable=True)
    last_delivery_status = Column(String(32), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(
        Integer, ForeignKey("webhook_subscriptions.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    target_url = Column(String(1024), nullable=False, default="")
    status = Column(String(16), nullable=False, default="pending", index=True)
    status_code = Column(Integer, nullable=True)
    attempts = Column(Integer, default=0)
    request_body = Column(Text, default="")
    response_body = Column(Text, default="")
    error_message = Column(Text, default="")
    duration_ms = Column(Float, default=0.0)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = Column(DateTime, nullable=True)
