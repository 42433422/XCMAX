"""Bounded recurring operation consent and reservation receipts."""

import sqlalchemy as sa

from alembic import op

revision = "2026_09_08_schedule_consent"
down_revision = "2026_09_08_agent_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "agent_schedule_authorizations" not in tables:
        op.create_table(
            "agent_schedule_authorizations",
            sa.Column("authorization_id", sa.String(96), primary_key=True),
            sa.Column("schedule_id", sa.String(96), nullable=False, index=True),
            sa.Column("user_id", sa.String(128), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("state", sa.String(24), nullable=False),
            sa.Column("scope_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.String(48), nullable=False),
            sa.Column("max_runs", sa.Integer(), nullable=False),
            sa.Column("reserved_runs", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(48), nullable=False),
        )
    if "agent_schedule_authorization_uses" not in tables:
        op.create_table(
            "agent_schedule_authorization_uses",
            sa.Column("run_id", sa.String(96), primary_key=True),
            sa.Column("authorization_id", sa.String(96), primary_key=True, index=True),
            sa.Column("created_at", sa.String(48), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("agent_schedule_authorization_uses")
    op.drop_table("agent_schedule_authorizations")
