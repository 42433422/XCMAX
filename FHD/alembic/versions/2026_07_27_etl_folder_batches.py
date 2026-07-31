"""Preserve folder batch and relative-path metadata for ETL uploads.

Revision ID: 2026_07_27_etl_folder_batches
Revises: 2026_07_27_po_tenant_unique
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_07_27_etl_folder_batches"
down_revision: str | Sequence[str] | None = "2026_07_26_general_etl_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "etl_uploads"
_BATCH_INDEX = "ix_etl_uploads_batch_id"


def _columns(bind) -> set[str]:
    if _TABLE not in sa.inspect(bind).get_table_names():
        return set()
    return {str(column["name"]) for column in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)
    if not columns:
        return
    with op.batch_alter_table(_TABLE, recreate="auto") as batch_op:
        if "batch_id" not in columns:
            batch_op.add_column(sa.Column("batch_id", sa.String(36), nullable=True))
        if "relative_path" not in columns:
            batch_op.add_column(sa.Column("relative_path", sa.String(500), nullable=True))

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(_TABLE)}
    if _BATCH_INDEX not in indexes:
        op.create_index(_BATCH_INDEX, _TABLE, ["batch_id"])


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)
    if not columns:
        return
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(_TABLE)}
    if _BATCH_INDEX in indexes:
        op.drop_index(_BATCH_INDEX, table_name=_TABLE)
    with op.batch_alter_table(_TABLE, recreate="auto") as batch_op:
        if "relative_path" in columns:
            batch_op.drop_column("relative_path")
        if "batch_id" in columns:
            batch_op.drop_column("batch_id")
