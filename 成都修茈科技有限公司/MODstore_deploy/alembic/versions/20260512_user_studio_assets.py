"""新增 user_studio_assets（工作台「我的素材」持久化索引）。

Revision ID: 20260512_user_studio_assets
Revises: 20260508_ai_employee_account
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260512_user_studio_assets"
down_revision = "20260508_ai_employee_account"
branch_labels = None
depends_on = None

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS user_studio_assets (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        kind VARCHAR(32) NOT NULL DEFAULT 'other',
        filename VARCHAR(512) NOT NULL DEFAULT '',
        mime_type VARCHAR(256) NOT NULL DEFAULT 'application/octet-stream',
        size_bytes INTEGER NOT NULL DEFAULT 0,
        storage_relpath VARCHAR(1024) NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW() NOT NULL
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_user_studio_assets_user_id ON user_studio_assets(user_id)""",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for sql in _DDL:
        sql = sql.strip()
        if sql:
            op.execute(sa.text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text("DROP TABLE IF EXISTS user_studio_assets CASCADE"))
