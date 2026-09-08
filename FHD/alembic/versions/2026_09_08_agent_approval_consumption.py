"""Persist one-use Agent approval identities."""

import sqlalchemy as sa

from alembic import op

revision = "2026_09_08_agent_approval"
down_revision = "2026_09_06_wechat_sync"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_approval_consumptions",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(96), nullable=False),
        sa.Column("step_id", sa.String(96), nullable=False),
        sa.Column("consumed_at", sa.String(48), nullable=False),
    )


def downgrade():
    op.drop_table("agent_approval_consumptions")
