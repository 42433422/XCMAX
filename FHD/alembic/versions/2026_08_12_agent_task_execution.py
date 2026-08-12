"""Add concurrent Agent task execution queue and repair legacy task uniqueness.

Revision ID: 2026_08_12_agent_task_execution
Revises: 2026_08_12_agent_task_ssot
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_12_agent_task_execution"
down_revision: str | Sequence[str] | None = "2026_08_12_agent_task_ssot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _names(rows: list[dict[str, object]]) -> set[str]:
    return {str(row.get("name") or "") for row in rows}


def _repair_task_uniqueness(bind) -> None:
    inspector = sa.inspect(bind)
    if "agent_tasks" not in inspector.get_table_names():
        return
    constraints = _names(inspector.get_unique_constraints("agent_tasks"))
    legacy = "uq_agent_tasks_user_task"
    expected = "uq_agent_tasks_tenant_user_task"
    if legacy in constraints:
        with op.batch_alter_table("agent_tasks") as batch:
            batch.drop_constraint(legacy, type_="unique")
        constraints.discard(legacy)
    if expected not in constraints:
        with op.batch_alter_table("agent_tasks") as batch:
            batch.create_unique_constraint(expected, ["tenant_id", "user_id", "task_id"])


def _create_execution_queue(bind) -> None:
    if "agent_task_executions" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "agent_task_executions",
            sa.Column("run_id", sa.String(length=96), primary_key=True),
            sa.Column("task_id", sa.String(length=160), nullable=False),
            sa.Column("user_id", sa.String(length=128), nullable=False),
            sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("state", sa.String(length=24), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("available_at", sa.String(length=48), nullable=False),
            sa.Column("lease_owner", sa.String(length=160), nullable=True),
            sa.Column("lease_expires_at", sa.String(length=48), nullable=True),
            sa.Column("heartbeat_at", sa.String(length=48), nullable=True),
            sa.Column("execution_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_by", sa.String(length=128), nullable=True),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.String(length=48), nullable=False),
            sa.Column("updated_at", sa.String(length=48), nullable=False),
            sa.Column("finished_at", sa.String(length=48), nullable=True),
        )
    indexes = _names(sa.inspect(bind).get_indexes("agent_task_executions"))
    definitions = {
        "ix_agent_task_executions_state": ["state"],
        "ix_agent_task_executions_available_at": ["available_at"],
        "ix_agent_task_executions_lease_expires_at": ["lease_expires_at"],
        "ix_agent_task_executions_updated_at": ["updated_at"],
        "ix_agent_task_executions_queue": ["state", "available_at", "priority", "created_at"],
        "ix_agent_task_executions_owner_lease": ["lease_owner", "lease_expires_at"],
        "ix_agent_task_executions_task_updated": ["task_id", "updated_at"],
    }
    for name, columns in definitions.items():
        if name not in indexes:
            op.create_index(name, "agent_task_executions", columns)


def upgrade() -> None:
    bind = op.get_bind()
    _repair_task_uniqueness(bind)
    _create_execution_queue(bind)


def downgrade() -> None:
    if "agent_task_executions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("agent_task_executions")
