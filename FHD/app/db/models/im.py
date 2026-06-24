"""企业内部 IM V0（自研薄层）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.mixins import TenantScopedMixin


class ImConversation(TenantScopedMixin, Base):
    __tablename__ = "im_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(255))
    is_direct: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)

    members: Mapped[list[ImConversationMember]] = relationship(
        "ImConversationMember", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list[ImMessage]] = relationship(
        "ImMessage", back_populates="conversation", cascade="all, delete-orphan"
    )


class ImConversationMember(TenantScopedMixin, Base):
    __tablename__ = "im_conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_im_conv_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("im_conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    last_read_message_id: Mapped[int | None] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())

    conversation: Mapped[ImConversation] = relationship("ImConversation", back_populates="members")


class ImMessage(TenantScopedMixin, Base):
    __tablename__ = "im_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("im_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), index=True
    )

    conversation: Mapped[ImConversation] = relationship("ImConversation", back_populates="messages")
