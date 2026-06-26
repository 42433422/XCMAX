"""新增 AI 员工账号池表（ai_employee_accounts）。

把外部账号（QQ 官方机器人、企业微信、邮箱等）抽象为 AI 员工名下的资产，
密钥落 ``_local_secrets/<platform>/<account_id>.json``，DB 只存索引/状态。

Revision ID: 20260508_ai_employee_account
Revises: 20260505_new_columns
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260508_ai_employee_account"
down_revision = "20260505_new_columns"
branch_labels = None
depends_on = None


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS ai_employee_accounts (
        id SERIAL PRIMARY KEY,
        platform VARCHAR(32) NOT NULL,
        external_id VARCHAR(128) NOT NULL,
        employee_id VARCHAR(128) NOT NULL,
        display_name VARCHAR(128) DEFAULT '',
        status VARCHAR(16) DEFAULT 'active' NOT NULL,
        sandbox BOOLEAN DEFAULT FALSE NOT NULL,
        secrets_path VARCHAR(512) DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
        last_seen_at TIMESTAMP
    )
    """,
    """CREATE INDEX IF NOT EXISTS ix_ai_employee_accounts_platform ON ai_employee_accounts(platform)""",
    """CREATE INDEX IF NOT EXISTS ix_ai_employee_accounts_external_id ON ai_employee_accounts(external_id)""",
    """CREATE INDEX IF NOT EXISTS ix_ai_employee_accounts_employee_id ON ai_employee_accounts(employee_id)""",
    """CREATE INDEX IF NOT EXISTS ix_ai_employee_accounts_status ON ai_employee_accounts(status)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_acc_platform_external ON ai_employee_accounts(platform, external_id)""",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite 走 Base.metadata.create_all（init_db），无需 DDL。
        return
    for sql in _DDL:
        sql = sql.strip()
        if sql:
            op.execute(sa.text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text("DROP TABLE IF EXISTS ai_employee_accounts CASCADE"))
