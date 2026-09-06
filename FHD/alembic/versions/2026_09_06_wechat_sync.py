"""Add wechat sync tables (contact identity + idempotent messages).

Revision ID: 2026_09_06_wechat_sync
Revises: 2026_09_05_etl_operation_lease
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_09_06_wechat_sync"
down_revision: str | Sequence[str] | None = "2026_09_05_etl_operation_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(inspector: sa.Inspector, name: str) -> bool:
    return name in set(inspector.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "wechat_contacts"):
        op.create_table(
            "wechat_contacts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("contact_key", sa.String(length=128), nullable=False, index=True),
            sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("wxid", sa.String(length=128), nullable=True),
            sa.Column("customer_id", sa.Integer(), nullable=True, index=True),
            sa.Column("match_status", sa.String(length=16), nullable=False, server_default="unlinked"),
            sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("tenant_id", "contact_key", name="uq_wechat_contact_key"),
        )

    if not _table_exists(inspector, "wechat_messages"):
        op.create_table(
            "wechat_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "contact_id",
                sa.Integer(),
                sa.ForeignKey("wechat_contacts.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("role", sa.String(length=8), nullable=False, server_default="other"),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("msg_ts", sa.DateTime(timezone=True), nullable=True, index=True),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="db"),
            sa.Column("dedupe_hash", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=True, index=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("dedupe_hash", name="uq_wechat_msg_hash"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _table_exists(inspector, "wechat_messages"):
        op.drop_table("wechat_messages")
    if _table_exists(inspector, "wechat_contacts"):
        op.drop_table("wechat_contacts")
