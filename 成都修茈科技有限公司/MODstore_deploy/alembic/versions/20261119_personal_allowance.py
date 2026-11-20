"""Persist verified mailbox ownership and backend-pinned promotion reservations."""

import sqlalchemy as sa

from alembic import op

revision = "20261119_personal_allowance"
down_revision = "20261119_xiaoc_followups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    schema = sa.inspect(bind)
    # Historical module-only databases can lack account/billing tables. Do not
    # invent partial parent tables or query their columns while upgrading them.
    has_users = schema.has_table("users")
    if has_users and "verified_email_sha256" not in {
        column["name"] for column in schema.get_columns("users")
    }:
        op.add_column("users", sa.Column("verified_email_sha256", sa.String(64), nullable=True))
    if (
        has_users
        and schema.has_table("plan_templates")
        and not schema.has_table("personal_plan_allowance_claims")
    ):
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
    schema = sa.inspect(op.get_bind())
    if schema.has_table("personal_plan_allowance_claims"):
        op.drop_table("personal_plan_allowance_claims")
    if schema.has_table("users") and "verified_email_sha256" in {
        column["name"] for column in schema.get_columns("users")
    }:
        op.drop_column("users", "verified_email_sha256")
