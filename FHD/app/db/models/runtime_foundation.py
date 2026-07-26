"""Migration-owned tables used by low-level runtime services."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiActionAudit(Base):
    __tablename__ = "ai_action_audit"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | list | str | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )


class MobileRelayDesktop(Base):
    __tablename__ = "mobile_relay_desktops"
    __table_args__ = (Index("ix_mobile_relay_desktops_user", "mobile_user_id"),)

    relay_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pairing_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    desktop_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    desktop_label: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    relay_base_url: Mapped[str] = mapped_column(String(512), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    mobile_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mobile_username: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    last_seen_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class MobileRelayTask(Base):
    __tablename__ = "mobile_relay_tasks"
    __table_args__ = (
        Index(
            "ix_mobile_relay_tasks_relay_status",
            "relay_id",
            "status",
            "created_at",
        ),
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    relay_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, server_default="codex.invoke")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="queued")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
