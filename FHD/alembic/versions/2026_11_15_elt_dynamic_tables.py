"""Add the generic dynamic tables used when AI infers a file's own schema.

不能归入固定业务目标的文件不再报错，改为把模型推断出的表结构写进
``elt_dynamic_tables``，行数据以 JSON 写进 ``elt_dynamic_rows``。表按
(tenant, owner, 表头指纹) 复用，行按 (table, row_hash) 去重。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2026_11_15_elt_dynamic_tables"
down_revision = "2026_11_15_elt_schema_reconcile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "elt_dynamic_tables" not in existing:
        op.create_table(
            "elt_dynamic_tables",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.Integer, nullable=False, index=True),
            sa.Column("owner_user_id", sa.Integer, nullable=False, index=True),
            sa.Column("name", sa.String(160), nullable=False, server_default=""),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("headers_json", sa.Text, nullable=False, server_default="[]"),
            sa.Column("columns_json", sa.Text, nullable=False, server_default="[]"),
            sa.Column("source_file", sa.String(255), nullable=True),
            sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "owner_user_id",
                "fingerprint",
                name="uq_elt_dynamic_table_owner_fingerprint",
            ),
        )
        op.create_index(
            "ix_elt_dynamic_table_owner", "elt_dynamic_tables", ["tenant_id", "owner_user_id"]
        )
    if "elt_dynamic_rows" not in existing:
        op.create_table(
            "elt_dynamic_rows",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "table_id",
                sa.String(36),
                sa.ForeignKey("elt_dynamic_tables.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("tenant_id", sa.Integer, nullable=False, index=True),
            sa.Column("owner_user_id", sa.Integer, nullable=False, index=True),
            sa.Column("run_id", sa.String(36), nullable=False),
            sa.Column("source_sheet", sa.String(160), nullable=False, server_default=""),
            sa.Column("source_row", sa.Integer, nullable=False, server_default="0"),
            sa.Column("row_hash", sa.String(64), nullable=False),
            sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("table_id", "row_hash", name="uq_elt_dynamic_row_hash"),
        )
        op.create_index("ix_elt_dynamic_row_run", "elt_dynamic_rows", ["run_id"])
        op.create_index(
            "ix_elt_dynamic_row_owner", "elt_dynamic_rows", ["tenant_id", "owner_user_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "elt_dynamic_rows" in existing:
        op.drop_table("elt_dynamic_rows")
    if "elt_dynamic_tables" in existing:
        op.drop_table("elt_dynamic_tables")
