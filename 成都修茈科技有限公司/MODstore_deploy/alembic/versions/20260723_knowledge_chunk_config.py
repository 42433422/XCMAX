"""add the knowledge collection chunking configuration column

Revision ID: 20260723_knowledge_chunk_config
Revises: 20260722_autonomy_decision_audit
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260723_knowledge_chunk_config"
down_revision = "20260722_autonomy_decision_audit"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return bool(sa.inspect(op.get_bind()).has_table(table))


def _column_exists(table: str, column: str) -> bool:
    if not _table_exists(table):
        return False
    return any(item["name"] == column for item in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if _table_exists("knowledge_collections") and not _column_exists(
        "knowledge_collections", "chunk_config"
    ):
        op.add_column(
            "knowledge_collections",
            sa.Column("chunk_config", sa.Text(), nullable=True, server_default=""),
        )


def downgrade() -> None:
    if _column_exists("knowledge_collections", "chunk_config"):
        op.drop_column("knowledge_collections", "chunk_config")
