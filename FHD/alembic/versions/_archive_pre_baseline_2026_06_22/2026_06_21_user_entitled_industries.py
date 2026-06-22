"""Add users.entitled_industries column (JSON/JSONB).

Revision ID: 2026_06_21_user_entitled_ind
Revises: 2026_06_21_butler_persy
Create Date: 2026-06-21

新增 users.entitled_industries 列：用户已开通的行业 id 列表（admin 分配）。
- PostgreSQL: JSONB
- 其他方言（SQLite 等）: JSON
 nullable=True, default=list（空列表）。
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "2026_06_21_user_entitled_ind"
down_revision: str | Sequence[str] | None = "2026_06_21_butler_persy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
    except Exception:  # noqa: BLE001 - 迁移幂等性检查需宽口径捕获（表/方言差异）
        return False
    return column in cols


def upgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "users", "entitled_industries"):
        return

    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        col_type = sa.JSONB()
    else:
        col_type = sa.JSON()

    op.add_column(
        "users",
        sa.Column(
            "entitled_industries",
            col_type,
            nullable=True,
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "users", "entitled_industries"):
        return
    op.drop_column("users", "entitled_industries")
