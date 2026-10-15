"""Durable correlation records; Para and customer delivery retain their own truth."""

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from modstore_server.db.base import Base


class MacControlTask(Base):
    __tablename__ = "mac_control_tasks"
    __table_args__ = (UniqueConstraint("actor", "request_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    para_task_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    device_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    attempt_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class MacControlEvent(Base):
    __tablename__ = "mac_control_events"
    __table_args__ = (UniqueConstraint("event_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class MacControlObservation(Base):
    __tablename__ = "mac_control_observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    observed_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    checked_at: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    error: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class MacControlSyncLease(Base):
    __tablename__ = "mac_control_sync_lease"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    until: Mapped[float] = mapped_column(Float, nullable=False, default=0)
