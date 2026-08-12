"""Add durable task SSOT and lifecycle command ledger.

Revision ID: 2026_08_12_agent_task_ssot
Revises: 2026_08_10_erp_absorb_orthogonal
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_12_agent_task_ssot"
down_revision: str | Sequence[str] | None = "2026_08_10_erp_absorb_orthogonal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _indexes(bind, table: str) -> set[str]:
    return {str(item["name"]) for item in sa.inspect(bind).get_indexes(table)}


def _ensure_index(bind, name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(bind, table):
        op.create_index(name, table, columns)


def _create_agent_tasks(bind) -> None:
    if "agent_tasks" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "agent_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("task_id", sa.String(length=160), nullable=False),
            sa.Column("user_id", sa.String(length=128), nullable=False),
            sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("source", sa.String(length=48), nullable=False, server_default="agent"),
            sa.Column("task_type", sa.String(length=48), nullable=False, server_default="agent"),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attention_state", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("active_run_id", sa.String(length=96), nullable=True),
            sa.Column("root_run_id", sa.String(length=96), nullable=True),
            sa.Column("conversation_id", sa.String(length=160), nullable=True),
            sa.Column("workspace_id", sa.String(length=160), nullable=True),
            sa.Column("workspace_path", sa.Text(), nullable=True),
            sa.Column(
                "workspace_isolation",
                sa.String(length=48),
                nullable=False,
                server_default="business_workspace",
            ),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("run_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("archived_at", sa.String(length=48), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(length=48), nullable=False),
            sa.Column("updated_at", sa.String(length=48), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "user_id",
                "task_id",
                name="uq_agent_tasks_tenant_user_task",
            ),
        )
    _ensure_index(bind, "ix_agent_tasks_status", "agent_tasks", ["status"])
    _ensure_index(bind, "ix_agent_tasks_active_run_id", "agent_tasks", ["active_run_id"])
    _ensure_index(bind, "ix_agent_tasks_conversation_id", "agent_tasks", ["conversation_id"])
    _ensure_index(bind, "ix_agent_tasks_created_at", "agent_tasks", ["created_at"])
    _ensure_index(bind, "ix_agent_tasks_updated_at", "agent_tasks", ["updated_at"])
    _ensure_index(bind, "ix_agent_tasks_user_updated", "agent_tasks", ["user_id", "updated_at"])
    _ensure_index(
        bind,
        "ix_agent_tasks_user_attention",
        "agent_tasks",
        ["user_id", "attention_state", "updated_at"],
    )
    _ensure_index(
        bind,
        "ix_agent_tasks_tenant_status",
        "agent_tasks",
        ["tenant_id", "status", "updated_at"],
    )


def _create_agent_task_commands(bind) -> None:
    if "agent_task_commands" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "agent_task_commands",
            sa.Column("command_id", sa.String(length=96), primary_key=True),
            sa.Column("task_id", sa.String(length=160), nullable=False),
            sa.Column("run_id", sa.String(length=96), nullable=False),
            sa.Column("action", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="requested"),
            sa.Column("requested_by", sa.String(length=128), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(length=48), nullable=False),
            sa.Column("applied_at", sa.String(length=48), nullable=True),
        )
    _ensure_index(bind, "ix_agent_task_commands_created_at", "agent_task_commands", ["created_at"])
    _ensure_index(
        bind,
        "ix_agent_task_commands_run_created",
        "agent_task_commands",
        ["run_id", "created_at"],
    )
    _ensure_index(
        bind,
        "ix_agent_task_commands_task_created",
        "agent_task_commands",
        ["task_id", "created_at"],
    )


def upgrade() -> None:
    bind = op.get_bind()
    _create_agent_tasks(bind)
    _create_agent_task_commands(bind)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "agent_task_commands" in tables:
        op.drop_table("agent_task_commands")
    if "agent_tasks" in tables:
        op.drop_table("agent_tasks")
