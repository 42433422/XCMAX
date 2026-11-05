"""Work Order SSOT 事件表（共享宿主多进程状态机）。

Revision ID: 20260910_work_order_events
Revises: 20260905_browser_handoff
"""

import sqlalchemy as sa
from alembic import op

revision = "20260910_work_order_events"
down_revision = "20260905_browser_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "work_order_events" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "work_order_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("wo_id", sa.String(32), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column("dedup_key", sa.String(96), nullable=False, server_default=""),
        sa.Column("reason", sa.String(64), nullable=False, server_default=""),
        sa.Column("context", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("from_state", sa.String(16), nullable=False, server_default=""),
        sa.Column("to_state", sa.String(16), nullable=False, server_default=""),
        sa.Column("ref", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("ts_unix", sa.Float(), nullable=False),
    )
    op.create_index("ix_work_order_events_wo_id", "work_order_events", ["wo_id"])
    op.create_index("ix_work_order_events_at", "work_order_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_work_order_events_at", table_name="work_order_events")
    op.drop_index("ix_work_order_events_wo_id", table_name="work_order_events")
    op.drop_table("work_order_events")
