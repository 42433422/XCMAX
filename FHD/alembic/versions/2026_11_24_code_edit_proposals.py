"""Persist existing code-editor proposals across workers and process restarts."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_24_code_edit_proposals"
down_revision = "2026_11_21_enterprise_cognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "code_edit_proposals" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "code_edit_proposals",
            sa.Column("edit_id", sa.String(40), primary_key=True),
            sa.Column(
                "owner_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.Integer(), nullable=True),
            sa.Column("workspace_root", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("apply_state", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_code_edit_proposals_owner", "code_edit_proposals", ["owner_user_id", "tenant_id"]
        )


def downgrade() -> None:
    # Retain pending work. Alembic invokes earlier revisions' own downgrade guards.
    pass
