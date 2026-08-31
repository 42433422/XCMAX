"""企业内部 IM V0（自研薄层）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ImConversation(Base):
    __tablename__ = "im_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(255))
    is_direct: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)

    members: Mapped[list[ImConversationMember]] = relationship(
        "ImConversationMember",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list[ImMessage]] = relationship(
        "ImMessage", back_populates="conversation", cascade="all, delete-orphan"
    )


class ImConversationMember(Base):
    __tablename__ = "im_conversation_members"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_im_conv_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("im_conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    last_read_message_id: Mapped[int | None] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    conversation: Mapped[ImConversation] = relationship(
        "ImConversation", back_populates="members"
    )


class ImMessage(Base):
    __tablename__ = "im_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("im_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # customer / ai / manual / system。客户端可忽略，管理端用来区分真实回复来源。
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    # 人工回复仍以 enterprise-cs 虚拟用户对客展示；实际操作人单独留痕。
    operator_user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), index=True
    )

    conversation: Mapped[ImConversation] = relationship(
        "ImConversation", back_populates="messages"
    )


class ImCustomerServiceAutomationState(Base):
    """企业专属客服 AI/人工接待状态（管理端 SSOT）。"""

    __tablename__ = "im_cs_automation_states"

    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("im_conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_active")
    transfer_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_customer_message_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_ai_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_operator_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
