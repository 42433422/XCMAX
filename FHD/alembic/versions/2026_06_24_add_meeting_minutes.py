"""add meeting_minutes table (小C 会议纪要 SSOT 三级派生)

Revision ID: 2026_06_24_meeting_minutes
Revises: 2026_06_22_baseline
Create Date: 2026-06-24

新增 ORM 表 ``meeting_minutes``（会议纪要 SSOT：raw → level1_script → level2_architecture
→ level3_plain）。仅用 dialect 无关类型（Text/String/Integer/DateTime），PG/SQLite 通用。

幂等：baseline 的 ``upgrade()`` 走 ``Base.metadata.create_all`` 覆盖**实时** ORM 元数据，
全新库在 baseline 阶段已建好本表，故此处先探测表是否存在再决定建/跳过——既适配全新库
（表已存在→跳过），也适配仅 stamp 到 baseline 的存量库（表缺失→补建）。
生产 ``FHD_SKIP_ALEMBIC=1`` 走 create_all，本迁移面向 dev/staging ``alembic upgrade head``。
索引命名与 SQLAlchemy ``index=True`` 默认（``ix_<table>_<col>``）一致，无漂移。
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_06_24_meeting_minutes"
down_revision: str | Sequence[str] | None = "2026_06_22_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "meeting_minutes"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        # 全新库：baseline 的 create_all 已建好本表（含索引），跳过避免重复建表报错。
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("raw_transcript", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("level1_script", sa.Text(), nullable=True),
        sa.Column("level2_architecture", sa.Text(), nullable=True),
        sa.Column("level3_plain", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meeting_minutes_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_meeting_minutes_user_id", _TABLE, ["user_id"])
    op.create_index("ix_meeting_minutes_source_hash", _TABLE, ["source_hash"])
    op.create_index("ix_meeting_minutes_status", _TABLE, ["status"])
    op.create_index("ix_meeting_minutes_user_status", _TABLE, ["user_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_meeting_minutes_user_status", table_name=_TABLE)
    op.drop_index("ix_meeting_minutes_status", table_name=_TABLE)
    op.drop_index("ix_meeting_minutes_source_hash", table_name=_TABLE)
    op.drop_index("ix_meeting_minutes_user_id", table_name=_TABLE)
    op.drop_index("ix_meeting_minutes_tenant_id", table_name=_TABLE)
    op.drop_table(_TABLE)
