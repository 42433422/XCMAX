from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text

from .models_base import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), default="")
    provider = Column(String(64), default="", index=True)
    model = Column(String(256), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
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
    charge_amount = Column(Numeric(12, 2), default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    charge_amount = Column(Numeric(12, 2), default=0)
    hold_no = Column(String(64), default="")
    upstream_status = Column(Integer, nullable=True)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
