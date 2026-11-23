"""Persist owner-scoped code proposals in the existing host database."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_24_code_edit_proposals"
down_revision = "2026_11_21_enterprise_cognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("code_edit_proposals"):
        op.create_table(
            "code_edit_proposals",
            sa.Column("edit_id", sa.String(64), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scope_json", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("state", sa.String(16), nullable=False),
        )


def downgrade() -> None:
    # Retain proposals and uncertain claims; rollback must not make them replayable.
    pass
