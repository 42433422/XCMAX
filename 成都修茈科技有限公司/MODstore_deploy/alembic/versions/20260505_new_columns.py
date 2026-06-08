"""既有表新增列：users、catalog_items、workflows、user_plans、知识库集合等。

Revision ID: 20260505_new_columns
Revises: 20260505_new_tables
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260505_new_columns"
down_revision = "20260505_new_tables"
branch_labels = None
depends_on = None


def _col_exists(bind, table: str, column: str) -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return result is not None


def _add_if_missing(bind, table: str, column: str, ddl: str) -> None:
    if not _col_exists(bind, table, column):
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # users 表
    _add_if_missing(bind, "users", "default_llm_json", "TEXT DEFAULT ''")
    _add_if_missing(bind, "users", "phone", "VARCHAR(32)")
    _add_if_missing(bind, "users", "experience", "INTEGER NOT NULL DEFAULT 0")

    # catalog_items 表
    for col, ddl in (
        ("industry",              "TEXT DEFAULT '通用'"),
        ("industry_code",         "TEXT DEFAULT ''"),
        ("industry_secondary",    "TEXT DEFAULT ''"),
        ("security_level",        "TEXT DEFAULT 'personal'"),
        ("description_embedding", "TEXT DEFAULT ''"),
        ("template_category",     "TEXT DEFAULT ''"),
        ("template_difficulty",   "TEXT DEFAULT ''"),
        ("install_count",         "INTEGER NOT NULL DEFAULT 0"),
        ("graph_snapshot",        "TEXT DEFAULT ''"),
        ("material_category",     "VARCHAR(64) DEFAULT ''"),
        ("license_scope",         "VARCHAR(32) DEFAULT 'personal'"),
        ("origin_type",           "VARCHAR(32) DEFAULT 'original'"),
        ("ip_risk_level",         "VARCHAR(16) DEFAULT 'low'"),
        ("compliance_status",     "VARCHAR(32) DEFAULT 'approved'"),
        ("rank_score",            "FLOAT DEFAULT 100.0"),
        ("delist_reason",         "TEXT DEFAULT ''"),
    ):
        _add_if_missing(bind, "catalog_items", col, ddl)

    # workflows 表
    for col, ddl in (
        ("migration_status", "TEXT DEFAULT ''"),
        ("migrated_to_id",   "INTEGER"),
        ("kind",             "TEXT DEFAULT ''"),
    ):
        _add_if_missing(bind, "workflows", col, ddl)

    # user_plans 表
    for col, ddl in (
        ("auto_renew",          "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("renewal_fail_reason", "TEXT DEFAULT ''"),
    ):
        _add_if_missing(bind, "user_plans", col, ddl)

    # knowledge_collections 表（在 new_tables migration 创建，此处补列以防并发/顺序问题）
    for col, ddl in (
        ("embedding_provider", "VARCHAR(64) DEFAULT ''"),
        ("embedding_source",   "VARCHAR(64) DEFAULT ''"),
    ):
        _add_if_missing(bind, "knowledge_collections", col, ddl)

    # account_experience_ledger 表
    _add_if_missing(bind, "account_experience_ledger", "description", "TEXT DEFAULT ''")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for col in ("default_llm_json", "phone", "experience"):
        if _col_exists(bind, "users", col):
            op.execute(sa.text(f"ALTER TABLE users DROP COLUMN IF EXISTS {col}"))

    for col in (
        "industry", "industry_code", "industry_secondary", "security_level",
        "description_embedding", "template_category", "template_difficulty",
        "install_count", "graph_snapshot",
        "material_category", "license_scope", "origin_type", "ip_risk_level",
        "compliance_status", "rank_score", "delist_reason",
    ):
        op.execute(sa.text(f"ALTER TABLE catalog_items DROP COLUMN IF EXISTS {col}"))

    for col in ("migration_status", "migrated_to_id", "kind"):
        op.execute(sa.text(f"ALTER TABLE workflows DROP COLUMN IF EXISTS {col}"))

    for col in ("auto_renew", "renewal_fail_reason"):
        op.execute(sa.text(f"ALTER TABLE user_plans DROP COLUMN IF EXISTS {col}"))

    for col in ("embedding_provider", "embedding_source"):
        op.execute(sa.text(f"ALTER TABLE knowledge_collections DROP COLUMN IF EXISTS {col}"))

    op.execute(sa.text("ALTER TABLE account_experience_ledger DROP COLUMN IF EXISTS description"))
