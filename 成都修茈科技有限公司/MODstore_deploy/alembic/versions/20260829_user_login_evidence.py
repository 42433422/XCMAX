"""Add canonical user login evidence timestamps.

Revision ID: 20260829_user_login_evidence
Revises: 20260815_account_lifecycle
"""

import sqlalchemy as sa

from alembic import op

revision = "20260829_user_login_evidence"
down_revision = "20260815_account_lifecycle"
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
    if "first_login_at" not in columns:
        op.add_column("users", sa.Column("first_login_at", sa.DateTime(), nullable=True))
    if "last_login_at" not in columns:
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    indexes = _indexes()
    if "ix_users_first_login_at" not in indexes:
        op.create_index("ix_users_first_login_at", "users", ["first_login_at"])
    if "ix_users_last_login_at" not in indexes:
        op.create_index("ix_users_last_login_at", "users", ["last_login_at"])


def downgrade() -> None:
    indexes = _indexes()
    if "ix_users_last_login_at" in indexes:
        op.drop_index("ix_users_last_login_at", table_name="users")
    if "ix_users_first_login_at" in indexes:
        op.drop_index("ix_users_first_login_at", table_name="users")
    columns = _columns()
    if "last_login_at" in columns:
        op.drop_column("users", "last_login_at")
    if "first_login_at" in columns:
        op.drop_column("users", "first_login_at")
