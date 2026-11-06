"""Add purchase_units.version for optimistic customer updates.

Revision ID: 2026_11_06_purchase_unit_version
Revises: 2026_11_06_task_lifecycle
Create Date: 2026-11-06

Existing rows receive version 1. Other customer columns are not rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_11_06_purchase_unit_version"
down_revision: str | Sequence[str] | None = "2026_11_06_task_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("purchase_units"):
        return
    existing = {str(row.get("name") or "") for row in inspector.get_columns("purchase_units")}
    if "version" in existing:
        return
    with op.batch_alter_table("purchase_units") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    # Resetting a version on re-upgrade would make stale pending writes valid
    # again. Older code can ignore the column; keep its concurrency history.
    pass
