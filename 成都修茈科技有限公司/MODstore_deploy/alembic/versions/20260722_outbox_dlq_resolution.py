"""retain auditable resolution state for outbox dead letters"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260722_outbox_dlq_resolution"
down_revision = "20260601_llm_official_prices"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    columns = (
        sa.Column("resolution_status", sa.String(32), nullable=True, server_default=""),
        sa.Column("resolution_action", sa.String(32), nullable=True, server_default=""),
        sa.Column("resolution_note", sa.Text(), nullable=True, server_default=""),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(), nullable=True),
        sa.Column("replay_outbox_id", sa.Integer(), nullable=True),
    )
    for column in columns:
        if not _column_exists("event_outbox_dlq", column.name):
            op.add_column("event_outbox_dlq", column)


def downgrade() -> None:
    for column in (
        "replay_outbox_id",
        "last_reconciled_at",
        "resolved_at",
        "resolution_note",
        "resolution_action",
        "resolution_status",
    ):
        if _column_exists("event_outbox_dlq", column):
            op.drop_column("event_outbox_dlq", column)
