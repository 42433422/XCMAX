"""Durable task lifecycle and idempotency records shared by task writers."""

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.db_base import Base


class TaskLifecycleRecord(Base):
    __tablename__ = "task_lifecycle_records"

    module: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    body_json: Mapped[str] = mapped_column(Text, nullable=False)


class TaskLifecycleIdempotency(Base):
    __tablename__ = "task_lifecycle_idempotency"

    module: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    idem_key: Mapped[str] = mapped_column(Text, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
