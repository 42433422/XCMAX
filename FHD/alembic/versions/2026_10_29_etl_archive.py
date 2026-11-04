"""Add isolated original archive metadata without changing existing retention."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2026_10_29_etl_archive"
down_revision = "2026_10_20_refund_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the historical schema independent of future ORM model changes.
    metadata = sa.MetaData()
    sa.Table(
        "etl_archive_quotas",
        metadata,
        sa.Column("tenant_id", sa.Integer(), primary_key=True),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    sa.Table(
        "etl_archive_assets",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("retention_mode", sa.String(16), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("tenant_id", sa.Integer(), index=True),
        sa.Index("ix_etl_archive_owner", "tenant_id", "owner_user_id"),
        sa.UniqueConstraint(
            "tenant_id", "owner_user_id", "request_key", name="uq_etl_archive_request"
        ),
    )
    sa.Table(
        "etl_archive_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.ForeignKey("etl_archive_assets.id"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("classification_id", sa.String(36)),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("tenant_id", sa.Integer(), index=True),
        sa.UniqueConstraint("asset_id", "version", name="uq_etl_archive_asset_version"),
        sa.UniqueConstraint(
            "tenant_id", "owner_user_id", "request_key", name="uq_etl_archive_version_request"
        ),
    )
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Archived originals and their references must not be destroyed on downgrade.
    pass
