"""Agent runtime persistence models."""

from __future__ import annotations

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_user_updated", "user_id", "updated_at"),
        Index("ix_agent_runs_status_updated", "status", "updated_at"),
    )

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intent: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    updated_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
