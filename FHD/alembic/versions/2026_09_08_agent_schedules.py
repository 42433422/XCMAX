"""Add durable account-owned recurring schedules.

Revision ID: 2026_09_08_agent_schedules
Revises: 2026_09_06_wechat_sync
"""

import sqlalchemy as sa

from alembic import op

revision = "2026_09_08_agent_schedules"
down_revision = "2026_09_06_wechat_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "agent_schedules" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "agent_schedules",
        sa.Column("schedule_id", sa.String(96), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("next_run_at", sa.String(48), nullable=False),
        sa.Column("lease_owner", sa.String(96), nullable=False),
        sa.Column("lease_expires_at", sa.String(48), nullable=False),
        sa.Column("last_task_id", sa.String(160), nullable=False),
        sa.Column("last_error", sa.String(96), nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
    )
    op.create_index("ix_agent_schedules_due", "agent_schedules", ["state", "next_run_at"])
    op.create_index("ix_agent_schedules_account", "agent_schedules", ["tenant_id", "user_id"])


def downgrade() -> None:
    op.drop_table("agent_schedules")
