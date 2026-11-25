"""Keep verified account licenses separate from a shared tenant plan."""

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from alembic import op

revision = "2026_11_24_account_license"
down_revision = "2026_11_21_enterprise_cognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("users"):
        raise RuntimeError("Account license migration requires the original users table")
    columns = {column["name"] for column in inspector.get_columns("users")}
    for column in (
        sa.Column("account_license_plan_id", sa.String(64), nullable=True),
        sa.Column("account_license_expires_at", sa.DateTime(), nullable=True),
    ):
        if column.name not in columns:
            op.add_column("users", column)


def downgrade() -> None:
    # Old code would reuse the tenant's stronger grant or ignore a personal
    # trial deadline. Do not move the version stamp after account state is used.
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if inspector.has_table("users") and "account_license_plan_id" in {
        column["name"] for column in inspector.get_columns("users")
    }:
        if connection.execute(
            sa.text("SELECT 1 FROM users WHERE account_license_plan_id IS NOT NULL LIMIT 1")
        ).first():
            raise RuntimeError("Account license projections require their compatible reader")
    # Retain nullable projection columns, just like the existing receipt and
    # conversation migrations, and keep the original parent delivery guards.
    context = op.get_context()
    parent = ScriptDirectory.from_config(context.config).get_revision(down_revision)
    if parent is None:
        raise RuntimeError("Account license migration is missing its delivery-safety parent")
    parent.module.downgrade()
