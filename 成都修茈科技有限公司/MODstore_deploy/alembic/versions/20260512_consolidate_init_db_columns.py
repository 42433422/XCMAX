"""将 init_db() 中的手动 ALTER ADD 列迁移统一到 Alembic。

此迁移覆盖以下变更：
- knowledge_collections: embedding_provider, embedding_source
- catalog_items: material_category, license_scope, origin_type, ip_risk_level,
  compliance_status, rank_score, delist_reason, industry, security_level,
  industry_code, industry_secondary, description_embedding, template_category,
  template_difficulty, install_count, graph_snapshot
- users: default_llm_json, phone, experience
- workflows: migration_status, migrated_to_id, kind
- user_plans: auto_renew, renewal_fail_reason
- employee_change_requests: git_branch, base_commit_sha, staged_commit_sha,
  approval_required_globs_json
- employee_trigger_bindings: priority

Revision ID: 20260512_consolidate_init_db_columns
Revises: 20260512_user_studio_assets
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260512_consolidate_init_db_columns"
down_revision = "20260512_user_studio_assets"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).first()
    return result is not None


def _add_col(table: str, column: str, col_type: sa.Column) -> None:
    if not _col_exists(table, column):
        op.add_column(table, col_type)


def upgrade() -> None:
    bind = op.get_bind()

    for col_name, col_def in [
        ("embedding_provider", sa.Column("embedding_provider", sa.String(64), server_default="")),
        ("embedding_source", sa.Column("embedding_source", sa.String(64), server_default="")),
    ]:
        _add_col("knowledge_collections", col_name, col_def)

    for col_name, col_def in [
        ("material_category", sa.Column("material_category", sa.String(64), server_default="")),
        ("license_scope", sa.Column("license_scope", sa.String(32), server_default="personal")),
        ("origin_type", sa.Column("origin_type", sa.String(32), server_default="original")),
        ("ip_risk_level", sa.Column("ip_risk_level", sa.String(16), server_default="low")),
        ("compliance_status", sa.Column("compliance_status", sa.String(32), server_default="approved")),
        ("rank_score", sa.Column("rank_score", sa.Float(), server_default="100.0")),
        ("delist_reason", sa.Column("delist_reason", sa.Text(), server_default="")),
        ("industry", sa.Column("industry", sa.Text(), server_default="通用")),
        ("security_level", sa.Column("security_level", sa.Text(), server_default="personal")),
        ("industry_code", sa.Column("industry_code", sa.Text(), server_default="")),
        ("industry_secondary", sa.Column("industry_secondary", sa.Text(), server_default="")),
        ("description_embedding", sa.Column("description_embedding", sa.Text(), server_default="")),
        ("template_category", sa.Column("template_category", sa.Text(), server_default="")),
        ("template_difficulty", sa.Column("template_difficulty", sa.Text(), server_default="")),
        ("install_count", sa.Column("install_count", sa.Integer(), server_default="0", nullable=False)),
        ("graph_snapshot", sa.Column("graph_snapshot", sa.Text(), server_default="")),
    ]:
        _add_col("catalog_items", col_name, col_def)

    for col_name, col_def in [
        ("default_llm_json", sa.Column("default_llm_json", sa.Text(), server_default="")),
        ("phone", sa.Column("phone", sa.Text())),
        ("experience", sa.Column("experience", sa.Integer(), server_default="0", nullable=False)),
    ]:
        _add_col("users", col_name, col_def)

    for col_name, col_def in [
        ("migration_status", sa.Column("migration_status", sa.Text(), server_default="")),
        ("migrated_to_id", sa.Column("migrated_to_id", sa.Integer())),
        ("kind", sa.Column("kind", sa.Text(), server_default="")),
    ]:
        _add_col("workflows", col_name, col_def)

    for col_name, col_def in [
        ("auto_renew", sa.Column("auto_renew", sa.Boolean(), server_default=sa.text("1"), nullable=False)),
        ("renewal_fail_reason", sa.Column("renewal_fail_reason", sa.Text(), server_default="")),
    ]:
        _add_col("user_plans", col_name, col_def)

    for col_name, col_def in [
        ("git_branch", sa.Column("git_branch", sa.String(256), server_default="")),
        ("base_commit_sha", sa.Column("base_commit_sha", sa.String(64), server_default="")),
        ("staged_commit_sha", sa.Column("staged_commit_sha", sa.String(64), server_default="")),
        ("approval_required_globs_json", sa.Column("approval_required_globs_json", sa.Text(), server_default="[]")),
    ]:
        _add_col("employee_change_requests", col_name, col_def)

    _add_col(
        "employee_trigger_bindings",
        "priority",
        sa.Column("priority", sa.Integer(), server_default="5", nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name != "sqlite"

    for col in ["embedding_provider", "embedding_source"]:
        if _col_exists("knowledge_collections", col):
            op.drop_column("knowledge_collections", col)

    for col in [
        "material_category", "license_scope", "origin_type", "ip_risk_level",
        "compliance_status", "rank_score", "delist_reason", "industry",
        "security_level", "industry_code", "industry_secondary",
        "description_embedding", "template_category", "template_difficulty",
        "install_count", "graph_snapshot",
    ]:
        if _col_exists("catalog_items", col):
            op.drop_column("catalog_items", col)

    for col in ["default_llm_json", "phone", "experience"]:
        if _col_exists("users", col):
            op.drop_column("users", col)

    for col in ["migration_status", "migrated_to_id", "kind"]:
        if _col_exists("workflows", col):
            op.drop_column("workflows", col)

    for col in ["auto_renew", "renewal_fail_reason"]:
        if _col_exists("user_plans", col):
            op.drop_column("user_plans", col)

    for col in ["git_branch", "base_commit_sha", "staged_commit_sha", "approval_required_globs_json"]:
        if _col_exists("employee_change_requests", col):
            op.drop_column("employee_change_requests", col)

    if _col_exists("employee_trigger_bindings", "priority"):
        op.drop_column("employee_trigger_bindings", "priority")
