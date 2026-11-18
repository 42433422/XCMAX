"""Fence late conversation writes after deletion or withdrawal."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_19_chat_revision"
down_revision = "2026_11_16_elt_value_cutover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ai_conversation_sessions"):
        return
    columns = {column["name"] for column in inspector.get_columns("ai_conversation_sessions")}
    if "revision" not in columns:
        op.add_column(
            "ai_conversation_sessions",
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        )
    if "deleted_at" not in columns:
        op.add_column("ai_conversation_sessions", sa.Column("deleted_at", sa.DateTime()))
    if inspector.has_table("ai_conversations"):
        indexes = {index["name"] for index in inspector.get_indexes("ai_conversations")}
        if "ix_ai_conversations_owner_cursor" not in indexes:
            op.create_index(
                "ix_ai_conversations_owner_cursor",
                "ai_conversations",
                ["session_id", "user_id", "id"],
            )


def downgrade() -> None:
    # Tombstones must survive downgrade: old in-flight writers must not reclaim IDs.
    pass
