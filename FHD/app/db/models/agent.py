"""Agent runtime persistence models."""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
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


class AgentTaskRecord(Base):
    """Stable task identity; AgentRun rows are execution attempts beneath it."""

    __tablename__ = "agent_tasks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "task_id",
            name="uq_agent_tasks_tenant_user_task",
        ),
        Index("ix_agent_tasks_user_updated", "user_id", "updated_at"),
        Index("ix_agent_tasks_user_attention", "user_id", "attention_state", "updated_at"),
        Index("ix_agent_tasks_tenant_status", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False, default="agent")
    task_type: Mapped[str] = mapped_column(String(48), nullable=False, default="agent")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attention_state: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    active_run_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    root_run_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_isolation: Mapped[str] = mapped_column(
        String(48), nullable=False, default="business_workspace"
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[str | None] = mapped_column(String(48), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    updated_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)


class AgentTaskCommandRecord(Base):
    """Append-only durable lifecycle intent for a task execution attempt."""

    __tablename__ = "agent_task_commands"
    __table_args__ = (
        Index("ix_agent_task_commands_run_created", "run_id", "created_at"),
        Index("ix_agent_task_commands_task_created", "task_id", "created_at"),
    )

    command_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    run_id: Mapped[str] = mapped_column(String(96), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="requested")
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    applied_at: Mapped[str | None] = mapped_column(String(48), nullable=True)


class AgentTaskExecutionRecord(Base):
    """Durable queue row and renewable execution lease for one AgentRun."""

    __tablename__ = "agent_task_executions"
    __table_args__ = (
        Index(
            "ix_agent_task_executions_queue",
            "state",
            "available_at",
            "priority",
            "created_at",
        ),
        Index(
            "ix_agent_task_executions_owner_lease",
            "lease_owner",
            "lease_expires_at",
        ),
        Index("ix_agent_task_executions_task_updated", "task_id", "updated_at"),
    )

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    available_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(48), nullable=True)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recovery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    finished_at: Mapped[str | None] = mapped_column(String(48), nullable=True)
