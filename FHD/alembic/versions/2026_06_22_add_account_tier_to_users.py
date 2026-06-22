"""Add account_tier/budget_range to users and market_membership_tier to sessions.

Revision ID: 2026_06_22_account_tier
Revises: 2026_06_21_user_entitled_ind
Create Date: 2026-06-22

账号体系单一真相源 + 自动派生（维度 4 + 会员）：
- users.account_tier  VARCHAR(32) NULL —— 账号等级 normal|pro|max|ultra（仅 enterprise 有意义）
- users.budget_range  VARCHAR(32) NULL —— 注册预算区间，account_tier 的派生来源
- sessions.market_membership_tier VARCHAR(32) NULL —— 登录时从修茈市场会员等级同步

回填：现有 tier=enterprise 用户 account_tier 置为 'normal'（其余保持 NULL）。

幂等：列已存在则跳过；与 init_db.ensure_user_profile_columns /
ensure_sessions_account_meta_columns 的运行时补列等价。
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "2026_06_22_account_tier"
down_revision: str | Sequence[str] | None = "2026_06_21_user_entitled_ind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
    except Exception:
        return False
    return column in cols


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "users", "account_tier"):
        op.add_column("users", sa.Column("account_tier", sa.String(length=32), nullable=True))
    if not _column_exists(conn, "users", "budget_range"):
        op.add_column("users", sa.Column("budget_range", sa.String(length=32), nullable=True))
    if not _column_exists(conn, "sessions", "market_membership_tier"):
        op.add_column(
            "sessions",
            sa.Column("market_membership_tier", sa.String(length=32), nullable=True),
        )

    # 回填：企业用户默认 account_tier='normal'
    try:
        op.execute(
            "UPDATE users SET account_tier = 'normal' "
            "WHERE tier = 'enterprise' AND account_tier IS NULL"
        )
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "sessions", "market_membership_tier"):
        op.drop_column("sessions", "market_membership_tier")
    if _column_exists(conn, "users", "budget_range"):
        op.drop_column("users", "budget_range")
    if _column_exists(conn, "users", "account_tier"):
        op.drop_column("users", "account_tier")
