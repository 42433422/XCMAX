"""Create durable task lifecycle and idempotency records."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_06_task_lifecycle"
down_revision = "2026_10_29_etl_archive"
branch_labels = None
depends_on = None

_TABLES = (
    (
        "task_lifecycle_records",
        (
            sa.Column("module", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), primary_key=True),
            sa.Column("task_id", sa.Text(), primary_key=True),
            sa.Column("body_json", sa.Text(), nullable=False),
        ),
    ),
    (
        "task_lifecycle_idempotency",
        (
            sa.Column("module", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), primary_key=True),
            sa.Column("idem_key", sa.Text(), primary_key=True),
            sa.Column("fingerprint", sa.Text(), nullable=False),
            sa.Column("task_id", sa.Text(), nullable=False),
        ),
    ),
)


def upgrade():
    for name, columns in _TABLES:
        if not sa.inspect(op.get_bind()).has_table(name):
            op.create_table(name, *columns)


def downgrade():
    for name, _columns in reversed(_TABLES):
        op.drop_table(name)
