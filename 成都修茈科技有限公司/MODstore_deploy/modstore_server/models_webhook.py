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

from .models_base import Base


class WebhookSubscription(Base):
    """开发者级 Webhook 出站订阅。

    每个用户可创建多条订阅，按事件名匹配（``["*"]`` 表示订阅所有事件）。
    ``secret_encrypted`` 用 Fernet（``llm_crypto``）加密保存，签名时解出
    用于 HMAC-SHA256 计算（行为对齐 ``webhook_dispatcher._signature``）。
    """

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
    """单次 Webhook 投递记录，用于审计和手动重试。

    与 ``webhook_dispatcher`` 落盘到磁盘的 ``webhook_events/*.json`` 区别：
    后者是默认全局 URL 投递的"事件存档"，仅按 event_id 一份；
    这里按 (subscription, attempt) 维度记录，便于开发者面板浏览。
    """

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


class OutboxEvent(Base):
    """事务型事件 outbox。

    业务事务内同库写入这张表 + 业务表，再由独立 dispatcher 拉取并通过
    NeuroBus / Webhook 投递。``status`` 流转：``pending`` → ``dispatched`` /
    ``failed``，失败带 ``last_error`` 与 ``attempts`` 供重试与告警。
    """

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    dispatched_at = Column(DateTime, nullable=True)
