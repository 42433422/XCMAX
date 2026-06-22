# FHD/app/infrastructure/persona/models.py
"""Persona DB ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class PersonaProfileModel(TimestampMixin, Base):
    """Persona 画像持久化模型。"""

    __tablename__ = "persona_profile"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    industry: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_name: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_domain: Mapped[str] = mapped_column(String(32), nullable=False)
    rapport_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    warmth: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    detail: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    proactivity: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    structure: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    interaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    business_domain_counts: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    emotion_signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PersonaEventLogModel(Base):
    """Persona 事件日志模型（审计 + L3 复盘）。"""

    __tablename__ = "persona_event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_data: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
