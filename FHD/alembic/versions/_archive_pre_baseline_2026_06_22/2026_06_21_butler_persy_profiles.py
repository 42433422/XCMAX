"""butler_user_profiles table for 拟人 Persy 系统

Revision ID: 2026_06_21_butler_persy
Revises: 2026_06_07_audit_ts
Create Date: 2026-06-21

新增 butler_user_profiles 表，存储 Butler 个性化人设：
- 身份层（identity_primary / identity_composite / identity_vector_json）
- MBTI 人格层（mbti_ei/sn/tf/jp + mbti_type + mbti_confidence）
- 互动元数据（interaction_count / last_inferred_at）

注：四轴参数（亲切度/详细度/主动度/结构度）由 MBTI 派生，不落库。
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "2026_06_21_butler_persy"
down_revision: str | Sequence[str] | None = "2026_06_07_audit_ts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "butler_user_profiles"):
        return

    op.create_table(
        "butler_user_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "identity_primary", sa.String(length=32), nullable=False, server_default="忠诚伙伴"
        ),
        sa.Column("identity_composite", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("identity_vector_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("mbti_ei", sa.Integer(), nullable=False, server_default="65"),
        sa.Column("mbti_sn", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("mbti_tf", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("mbti_jp", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("mbti_type", sa.String(length=4), nullable=False, server_default="ENFJ"),
        sa.Column("mbti_confidence", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("last_inferred_at", sa.DateTime(), nullable=True),
        sa.Column("interaction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_butler_profile_user"),
        sa.PrimaryKeyConstraint("user_id", name="pk_butler_user_profiles"),
    )
    op.create_index(
        "ix_butler_user_profiles_user_id",
        "butler_user_profiles",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "butler_user_profiles"):
        return
    op.drop_index("ix_butler_user_profiles_user_id", table_name="butler_user_profiles")
    op.drop_table("butler_user_profiles")
