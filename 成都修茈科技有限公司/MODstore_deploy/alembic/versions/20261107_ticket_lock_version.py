"""Add the optimistic lock used by ticket writes and approvals."""

import sqlalchemy as sa

from alembic import op

revision = "20261107_ticket_lock_version"
down_revision = "20261020_merge_ticket_incident"
branch_labels = None
depends_on = None

_TABLES = ("customer_service_tickets", "customer_service_actions")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        columns = {str(row["name"]) for row in inspector.get_columns(table)}
        if "lock_version" in columns:
            continue
        op.add_column(
            table,
            sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        columns = {str(row["name"]) for row in inspector.get_columns(table)}
        if "lock_version" in columns:
            op.drop_column(table, "lock_version")
