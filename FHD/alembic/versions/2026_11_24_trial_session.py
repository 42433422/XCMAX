"""Keep the original verified trial deadline with its host session."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_24_trial_session"
down_revision = "2026_11_24_code_edit_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "sessions" in inspector.get_table_names() and "verified_trial_expires_at" not in {
        column["name"] for column in inspector.get_columns("sessions")
    }:
        op.add_column(
            "sessions", sa.Column("verified_trial_expires_at", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    # Keep evidence; only an authenticated grant may populate a previously unknown deadline.
    pass
