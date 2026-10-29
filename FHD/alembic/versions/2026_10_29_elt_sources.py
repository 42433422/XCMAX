"""Retained ELT source assets and immutable source versions.

Revision ID: 2026_10_29_elt_sources
Revises: 2026_10_20_refund_permission
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2026_10_29_elt_sources"
down_revision = "2026_10_20_refund_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The squashed baseline creates current ORM metadata on fresh installations.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "elt_source_assets" not in existing:
        op.create_table(
            "elt_source_assets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_elt_source_assets_tenant_id", "elt_source_assets", ["tenant_id"])
        op.create_index(
            "ix_elt_source_assets_owner_user_id", "elt_source_assets", ["owner_user_id"]
        )
        op.create_index(
            "ix_elt_source_asset_owner", "elt_source_assets", ["tenant_id", "owner_user_id"]
        )
    if "elt_source_revisions" not in existing:
        op.create_table(
            "elt_source_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), nullable=False),
            sa.Column(
                "asset_id", sa.String(36), sa.ForeignKey("elt_source_assets.id"), nullable=False
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("upload_id", sa.String(36), sa.ForeignKey("etl_uploads.id"), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("asset_id", "version", name="uq_elt_source_revision_version"),
            sa.UniqueConstraint("upload_id", name="uq_elt_source_revision_upload"),
        )
        for column in ("tenant_id", "owner_user_id", "asset_id"):
            op.create_index(f"ix_elt_source_revisions_{column}", "elt_source_revisions", [column])
        op.create_index(
            "ix_elt_source_revision_owner",
            "elt_source_revisions",
            ["tenant_id", "owner_user_id", "asset_id"],
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("elt_source_revisions", "elt_source_assets"):
        if table in existing:
            op.drop_table(table)
