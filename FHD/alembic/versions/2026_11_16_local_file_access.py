"""Add local file read-only grants and per-file index state.

桌面端「本机文件（只读）」授权需要两张表：授权记录与逐文件索引指纹。
迁移保持幂等：表已由 ORM 首启创建时直接跳过。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2026_11_16_local_file_access"
down_revision = "2026_11_15_elt_dynamic_tables"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _has_table("local_file_grants"):
        op.create_table(
            "local_file_grants",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
            sa.Column("owner_user_id", sa.Integer(), nullable=False, index=True),
            sa.Column("device_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("mode", sa.String(16), nullable=False, server_default="folder"),
            sa.Column("root_path", sa.Text(), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("authorized_via", sa.String(32), nullable=False, server_default="desktop"),
            sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scan_status", sa.String(24), nullable=False, server_default="idle"),
            sa.Column("scan_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "tenant_id", "owner_user_id", "root_path", name="uq_local_file_grant_root"
            ),
        )
        op.create_index(
            "ix_local_file_grants_owner", "local_file_grants", ["tenant_id", "owner_user_id"]
        )

    if not _has_table("local_file_documents"):
        op.create_table(
            "local_file_documents",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
            sa.Column("owner_user_id", sa.Integer(), nullable=False, index=True),
            sa.Column(
                "grant_id",
                sa.Integer(),
                sa.ForeignKey("local_file_grants.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("path", sa.Text(), nullable=False),
            sa.Column("relative_path", sa.Text(), nullable=False, server_default=""),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mtime_ns", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
            sa.Column("document_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("dataset_id", sa.String(64), nullable=False, server_default="local-files"),
            sa.Column("status", sa.String(16), nullable=False, server_default="indexed"),
            sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("grant_id", "path", name="uq_local_file_document_path"),
        )
        op.create_index(
            "ix_local_file_documents_grant_status",
            "local_file_documents",
            ["grant_id", "status"],
        )
        op.create_index(
            "ix_local_file_documents_document_id",
            "local_file_documents",
            ["document_id"],
        )


def downgrade() -> None:
    if _has_table("local_file_documents"):
        op.drop_table("local_file_documents")
    if _has_table("local_file_grants"):
        op.drop_table("local_file_grants")
