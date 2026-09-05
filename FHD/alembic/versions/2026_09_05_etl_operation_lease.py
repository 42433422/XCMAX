"""Persist recoverable, fenced ETL operation ownership.

Revision ID: 2026_09_05_etl_operation_lease
Revises: 2026_08_31_enterprise_cs_ai
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_09_05_etl_operation_lease"
down_revision: str | Sequence[str] | None = "2026_08_31_enterprise_cs_ai"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "etl_runs" not in sa.inspect(bind).get_table_names():
        return
    existing = {item["name"] for item in sa.inspect(bind).get_columns("etl_runs")}
    with op.batch_alter_table("etl_runs", recreate="auto") as batch:
        for column in (
            sa.Column("operation_kind", sa.String(16), nullable=True),
            sa.Column("operation_token", sa.String(36), nullable=True),
            sa.Column("operation_lease_until", sa.DateTime(timezone=True), nullable=True),
        ):
            if column.name not in existing:
                batch.add_column(column)


def downgrade() -> None:
    bind = op.get_bind()
    if "etl_runs" not in sa.inspect(bind).get_table_names():
        return
    existing = {item["name"] for item in sa.inspect(bind).get_columns("etl_runs")}
    # Supported packaged SQLite uses native DROP COLUMN. Rebuilding the parent
    # table would violate etl_run_rows foreign keys even though these columns are unrelated.
    for name in ("operation_lease_until", "operation_token", "operation_kind"):
        if name in existing:
            op.drop_column("etl_runs", name)
