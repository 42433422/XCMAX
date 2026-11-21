"""One management XiaoC identity and append-only, evidence-backed experiences."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from modstore_server.db.db_base import Base


class XiaoCLifeState(Base):
    __tablename__ = "xiaoc_life_state"

    identity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class XiaoCLifeEvent(Base):
    __tablename__ = "xiaoc_life_events"
    __table_args__ = (Index("ix_xiaoc_life_events_identity_time", "identity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey("xiaoc_life_state.identity_id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


__all__ = ["XiaoCLifeEvent", "XiaoCLifeState"]
