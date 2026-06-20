from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.ai import AIConversationSession
    from app.db.models.miniprogram import MpFeedback, MpOrder


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(
        "password", String, nullable=False, comment="hashed password (PBKDF2 or legacy SHA256)"
    )
    display_name: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    wx_openid: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    wx_unionid: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    wx_avatar_url: Mapped[Optional[str]] = mapped_column(Text)
    mp_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mp_nickname: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # 用户等级与行业（管理端可编辑，复用 industryPresets 行业 id）
    tier: Mapped[str] = mapped_column(String(32), default="personal", nullable=False, comment="用户等级: personal|enterprise|admin")
    industry_id: Mapped[str] = mapped_column(String(32), default="通用", nullable=False, comment="行业 id，引用 industryPresets")

    created_user: Mapped[Optional[User]] = relationship(
        "User", remote_side=[id], backref="created_users", foreign_keys=[created_by]
    )
    sessions: Mapped[list[Session]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    ai_conversation_sessions: Mapped[list[AIConversationSession]] = relationship(
        "AIConversationSession", back_populates="user", cascade="all, delete-orphan"
    )
    mp_orders: Mapped[list[MpOrder]] = relationship(
        "MpOrder", back_populates="user", cascade="all, delete-orphan"
    )
    mp_feedbacks: Mapped[list[MpFeedback]] = relationship(
        "MpFeedback",
        foreign_keys="MpFeedback.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    market_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entitled_mod_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_kind: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, default="enterprise"
    )
    company_brand: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, default="")
    market_is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    market_is_enterprise: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    impersonating_market_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    impersonating_username: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, default=""
    )
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    user: Mapped[User] = relationship("User", back_populates="sessions")
