"""Durable correlation records; Para and customer delivery retain their own truth."""

from sqlalchemy import Column, Float, Integer, String, Text, UniqueConstraint

from modstore_server.db.base import Base


class MacControlTask(Base):
    __tablename__ = "mac_control_tasks"
    __table_args__ = (UniqueConstraint("actor", "request_key"),)

    id = Column(String(64), primary_key=True)
    actor = Column(String(128), nullable=False)
    request_key = Column(String(128), nullable=False)
    request_digest = Column(String(64), nullable=False)
    request_json = Column(Text, nullable=False)
    state = Column(String(40), nullable=False, default="queued", index=True)
    reason = Column(String(256), nullable=False, default="")
    para_task_id = Column(String(128), nullable=False, default="")
    device_id = Column(String(128), nullable=False, default="")
    attempt_id = Column(String(64), nullable=False, default="")
    lease_until = Column(Float, nullable=False, default=0)
    snapshot_json = Column(Text, nullable=False, default="{}")
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)


class MacControlEvent(Base):
    __tablename__ = "mac_control_events"
    __table_args__ = (UniqueConstraint("event_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(String(128), nullable=False)
    task_id = Column(String(64), nullable=False, index=True)
    attempt_id = Column(String(64), nullable=False, default="")
    state = Column(String(40), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(Float, nullable=False)


class MacControlObservation(Base):
    __tablename__ = "mac_control_observations"

    id = Column(String(64), primary_key=True)
    payload_json = Column(Text, nullable=False, default="{}")
    observed_at = Column(Float, nullable=False, default=0)
    checked_at = Column(Float, nullable=False, default=0)
    error = Column(String(128), nullable=False, default="")


class MacControlSyncLease(Base):
    __tablename__ = "mac_control_sync_lease"

    id = Column(String(32), primary_key=True)
    owner = Column(String(64), nullable=False, default="")
    until = Column(Float, nullable=False, default=0)
