"""tenants 试用/套餐列 + users.tenant_id 确认

Revision ID: 2026_06_05_tenant_saas
Revises: 2026_06_05_ai_evidence
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "2026_06_05_tenant_saas"
down_revision: Union[str, Sequence[str], None] = "2026_06_05_ai_evidence"
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
    if _table_exists(conn, "tenants"):
        if not _column_exists(conn, "tenants", "trial_started_at"):
            op.add_column("tenants", sa.Column("trial_started_at", sa.DateTime(), nullable=True))
        if not _column_exists(conn, "tenants", "trial_expires_at"):
            op.add_column("tenants", sa.Column("trial_expires_at", sa.DateTime(), nullable=True))
        if not _column_exists(conn, "tenants", "plan_id"):
            op.add_column("tenants", sa.Column("plan_id", sa.String(64), nullable=True))

    if _table_exists(conn, "users") and not _column_exists(conn, "users", "tenant_id"):
        op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "users") and _column_exists(conn, "users", "tenant_id"):
        op.drop_index("ix_users_tenant_id", table_name="users")
        op.drop_column("users", "tenant_id")
    if _table_exists(conn, "tenants"):
        for col in ("plan_id", "trial_expires_at", "trial_started_at"):
            if _column_exists(conn, "tenants", col):
                op.drop_column("tenants", col)
