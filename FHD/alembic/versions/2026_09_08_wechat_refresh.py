"""Add the durable WeChat collector request and receipt outbox."""

import sqlalchemy as sa

from alembic import op

revision = "2026_09_08_wechat_refresh"
down_revision = "2026_09_08_schedule_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "wechat_refresh_requests" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "wechat_refresh_requests",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=False),
        sa.Column("lease_until", sa.Float(), nullable=False),
        sa.Column("receipt_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_wechat_refresh_due", "wechat_refresh_requests", ["tenant_id", "state", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("wechat_refresh_requests")
