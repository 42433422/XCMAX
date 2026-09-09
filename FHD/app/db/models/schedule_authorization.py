"""Bounded recurring-operation consent and per-run reservation receipts."""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduleAuthorizationRecord(Base):
    __tablename__ = "agent_schedule_authorizations"

    authorization_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    schedule_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(48), nullable=False)
    max_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)


class ScheduleAuthorizationUseRecord(Base):
    __tablename__ = "agent_schedule_authorization_uses"

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(String(96), primary_key=True, index=True)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
