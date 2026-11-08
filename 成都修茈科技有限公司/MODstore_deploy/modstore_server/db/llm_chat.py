"""BYOK、聊天会话与计费日志。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from modstore_server.db.db_base import Base


class UserLlmCredential(Base):
    __tablename__ = "user_llm_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_llm_provider"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=False)
    api_key_encrypted = Column(Text, nullable=False, default="")
    base_url_encrypted = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), default="")
    provider = Column(String(64), default="", index=True)
    model = Column(String(256), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer, ForeignKey("chat_conversations.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, default="")
    provider = Column(String(64), default="")
    model = Column(String(256), default="")
    usage_json = Column(Text, default="{}")
    charge_amount = Column(Numeric(12, 2), default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(
        Integer, ForeignKey("chat_conversations.id"), nullable=True, index=True
    )
    provider = Column(String(64), nullable=False, index=True)
    model = Column(String(256), nullable=False)
    status = Column(String(32), default="success", index=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated = Column(Boolean, default=False)
    charge_amount = Column(Numeric(12, 2), default=0.0)
    hold_no = Column(String(64), default="")
    upstream_status = Column(Integer, nullable=True)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class LlmClientRequest(Base):
    """One billed chat execution per client idempotency key (see llm_client_requests)."""

    __tablename__ = "llm_client_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id", name="uq_llm_client_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="processing")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    done_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
