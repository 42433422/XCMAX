"""Persist opted-in XiaoC delivery follow-ups and observation cursors."""

import sqlalchemy as sa

from alembic import op

revision = "20261119_xiaoc_followups"
down_revision = "20261108_llm_client_requests"
branch_labels = None
depends_on = None

TABLE = "xiaoc_delivery_followups"
INDEX = "ix_xiaoc_delivery_followups_due"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("customer_service_tickets.id"),
            primary_key=True,
        ),
        sa.Column("following", sa.Boolean(), nullable=False),
        sa.Column("last_observed", sa.String(64), nullable=False),
        sa.Column("next_check_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index(INDEX, TABLE, ["following", "next_check_at"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE):
        op.drop_index(INDEX, table_name=TABLE)
        op.drop_table(TABLE)
