"""Add durable paid-asset installation commands.

Revision ID: 20260904_asset_install_cmd
Revises: 20260904_enterprise_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260904_asset_install_cmd"
down_revision = "20260904_enterprise_identity"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("asset_install_commands"):
        return
    op.create_table(
        "asset_install_commands",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purchase_id", sa.Integer(), sa.ForeignKey("purchases.id"), nullable=False),
        sa.Column("catalog_id", sa.Integer(), sa.ForeignKey("catalog_items.id"), nullable=False),
        sa.Column("installation_id", sa.String(64), nullable=False, server_default="*"),
        sa.Column("idempotency_key", sa.String(192), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="user_click"),
        sa.Column("source_event_id", sa.String(192), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("idempotency_key", name="uq_asset_install_command_idempotency"),
    )
    for name, columns in (
        ("ix_asset_install_commands_user_id", ["user_id"]),
        ("ix_asset_install_commands_purchase_id", ["purchase_id"]),
        ("ix_asset_install_commands_catalog_id", ["catalog_id"]),
        ("ix_asset_install_commands_installation_id", ["installation_id"]),
        ("ix_asset_install_commands_idempotency_key", ["idempotency_key"]),
        ("ix_asset_install_commands_source", ["source"]),
        ("ix_asset_install_commands_source_event_id", ["source_event_id"]),
        ("ix_asset_install_commands_status", ["status"]),
        ("ix_asset_install_commands_created_at", ["created_at"]),
    ):
        op.create_index(name, "asset_install_commands", columns)


def downgrade() -> None:
    if _table_exists("asset_install_commands"):
        op.drop_table("asset_install_commands")
