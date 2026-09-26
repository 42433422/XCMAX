"""One-use invitations to a tenant, bound to a verified market account."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantInvitation(Base):
    __tablename__ = "tenant_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True
    )
    inviter_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    target_username: Mapped[str] = mapped_column(String(128), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_market_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
