"""Add canonical account registration lifecycle state.

Revision ID: 20260815_account_lifecycle
Revises: 20260723_knowledge_chunk_config
"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_account_lifecycle"
down_revision = "20260723_knowledge_chunk_config"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {str(row["name"]) for row in sa.inspect(op.get_bind()).get_columns("users")}


def _indexes() -> set[str]:
    return {
        str(row["name"])
        for row in sa.inspect(op.get_bind()).get_indexes("users")
        if row.get("name")
    }


def upgrade() -> None:
    columns = _columns()
    if "account_state" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "account_state",
                sa.String(length=32),
                nullable=False,
                server_default="pending_plan",
            ),
        )
    if "ix_users_account_state" not in _indexes():
        op.create_index(
            "ix_users_account_state", "users", ["account_state"], unique=False
        )
    grant_conditions = ["is_admin = 1"]
    if "is_enterprise" in columns:
        grant_conditions.append("is_enterprise = 1")
    op.execute(
        "UPDATE users SET account_state = 'active' WHERE "
        + " OR ".join(grant_conditions)
    )


def downgrade() -> None:
    if "ix_users_account_state" in _indexes():
        op.drop_index("ix_users_account_state", table_name="users")
    if "account_state" in _columns():
        op.drop_column("users", "account_state")
