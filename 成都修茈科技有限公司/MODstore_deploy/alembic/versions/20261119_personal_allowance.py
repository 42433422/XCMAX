"""Persist verified mailbox ownership and backend-pinned promotion reservations."""

import sqlalchemy as sa

from alembic import op

revision = "20261119_personal_allowance"
down_revision = "20261119_xiaoc_followups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "verified_email_sha256" not in {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }:
        op.add_column("users", sa.Column("verified_email_sha256", sa.String(64), nullable=True))
    if not sa.inspect(bind).has_table("personal_plan_allowance_claims"):
        op.create_table(
            "personal_plan_allowance_claims",
            sa.Column(
                "plan_id", sa.String(64), sa.ForeignKey("plan_templates.id"), primary_key=True
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("identity_sha256", sa.String(64), nullable=False),
            sa.Column("backend", sa.String(8), nullable=False),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "plan_id", "identity_sha256", name="uq_personal_allowance_identity"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("personal_plan_allowance_claims"):
        op.drop_table("personal_plan_allowance_claims")
    if "verified_email_sha256" in {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }:
        op.drop_column("users", "verified_email_sha256")
