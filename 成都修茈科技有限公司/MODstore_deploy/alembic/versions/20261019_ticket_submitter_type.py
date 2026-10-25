"""工单提交人身份：建单固化管理员 / 客户，并回填历史工单。

Revision ID: 20261019_ticket_submitter
Revises: 20260910_work_order_events
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_ticket_submitter"
down_revision = "20260910_work_order_events"
branch_labels = None
depends_on = None

_TABLE = "customer_service_tickets"
_INDEX = "ix_customer_service_tickets_submitter_type"


def backfill_submitter_types(bind) -> None:
    """按 users.is_admin 回填；找不到用户的保留 unknown，不冒充客户。"""
    bind.execute(
        sa.text(
            "UPDATE customer_service_tickets SET submitter_type = CASE "
            "WHEN EXISTS (SELECT 1 FROM users WHERE users.id = customer_service_tickets.user_id "
            "AND users.is_admin = :admin) THEN 'admin' "
            "WHEN EXISTS (SELECT 1 FROM users WHERE users.id = customer_service_tickets.user_id) "
            "THEN 'customer' ELSE 'unknown' END "
            "WHERE submitter_type IS NULL OR submitter_type IN ('', 'unknown')"
        ),
        {"admin": True},
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {str(row["name"]) for row in inspector.get_columns(_TABLE)}
    if "submitter_type" not in columns:
        op.add_column(
            _TABLE,
            sa.Column(
                "submitter_type",
                sa.String(16),
                nullable=False,
                server_default="unknown",
            ),
        )
    indexes = {
        str(row["name"])
        for row in sa.inspect(bind).get_indexes(_TABLE)
        if row.get("name")
    }
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, ["submitter_type"])
    backfill_submitter_types(bind)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {
        str(row["name"])
        for row in sa.inspect(bind).get_indexes(_TABLE)
        if row.get("name")
    }
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    columns = {str(row["name"]) for row in sa.inspect(bind).get_columns(_TABLE)}
    if "submitter_type" in columns:
        op.drop_column(_TABLE, "submitter_type")
