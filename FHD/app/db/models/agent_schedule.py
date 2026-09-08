"""Host-owned recurring schedules, with a durable lease for occurrence publication."""

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentScheduleRecord(Base):
    __tablename__ = "agent_schedules"
    __table_args__ = (
        Index("ix_agent_schedules_due", "state", "next_run_at"),
        Index("ix_agent_schedules_account", "tenant_id", "user_id"),
    )

    schedule_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    next_run_at: Mapped[str] = mapped_column(String(48), nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    lease_expires_at: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    last_task_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(48), nullable=False)
