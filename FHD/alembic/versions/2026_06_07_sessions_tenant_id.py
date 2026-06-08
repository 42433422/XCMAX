"""sessions.tenant_id for login tenant binding

Revision ID: 2026_06_07_sessions_tenant
Revises: 2026_06_05_tenant_saas
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "2026_06_07_sessions_tenant"
down_revision: Union[str, Sequence[str], None] = "2026_06_05_tenant_saas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sessions") and not _column_exists(conn, "sessions", "tenant_id"):
        op.add_column("sessions", sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sessions") and _column_exists(conn, "sessions", "tenant_id"):
        op.drop_index("ix_sessions_tenant_id", table_name="sessions")
        op.drop_column("sessions", "tenant_id")
