"""Add enterprise customer-service AI routing state and reply provenance.

Revision ID: 2026_08_31_enterprise_cs_ai
Revises: 2026_08_20_repair_products_uom
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_31_enterprise_cs_ai"
down_revision: str | Sequence[str] | None = "2026_08_20_repair_products_uom"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "im_messages" in tables:
        columns = {
            str(row.get("name") or "") for row in inspector.get_columns("im_messages")
        }
        with op.batch_alter_table("im_messages", recreate="auto") as batch:
            if "origin" not in columns:
                batch.add_column(
                    sa.Column(
                        "origin",
                        sa.String(length=32),
                        nullable=False,
                        server_default="user",
                    )
                )
            if "operator_user_id" not in columns:
                batch.add_column(
                    sa.Column("operator_user_id", sa.Integer(), nullable=True)
                )
        inspector = sa.inspect(bind)
        indexes = {
            str(row.get("name") or "") for row in inspector.get_indexes("im_messages")
        }
        if "ix_im_messages_operator_user_id" not in indexes:
            op.create_index(
                "ix_im_messages_operator_user_id",
                "im_messages",
                ["operator_user_id"],
            )

    tables = set(sa.inspect(bind).get_table_names())
    if "im_cs_automation_states" not in tables:
        op.create_table(
            "im_cs_automation_states",
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column(
                "mode", sa.String(length=16), nullable=False, server_default="ai"
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="ai_active",
            ),
            sa.Column("transfer_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "last_customer_message_id",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "last_ai_message_id", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("last_operator_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["im_conversations.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("conversation_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "im_cs_automation_states" in tables:
        op.drop_table("im_cs_automation_states")
    if "im_messages" not in tables:
        return
    columns = {
        str(row.get("name") or "")
        for row in sa.inspect(bind).get_columns("im_messages")
    }
    indexes = {
        str(row.get("name") or "")
        for row in sa.inspect(bind).get_indexes("im_messages")
    }
    if "ix_im_messages_operator_user_id" in indexes:
        op.drop_index("ix_im_messages_operator_user_id", table_name="im_messages")
    with op.batch_alter_table("im_messages", recreate="auto") as batch:
        if "operator_user_id" in columns:
            batch.drop_column("operator_user_id")
        if "origin" in columns:
            batch.drop_column("origin")
