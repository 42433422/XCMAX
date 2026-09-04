"""Add verified enterprise identity to the internal customer ledger.

Revision ID: 20260904_enterprise_identity
Revises: 20260829_user_login_evidence
"""

import sqlalchemy as sa

from alembic import op

revision = "20260904_enterprise_identity"
down_revision = "20260829_user_login_evidence"
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
    additions = (
        sa.Column("enterprise_subject_id", sa.String(128), nullable=True),
        sa.Column("enterprise_legal_name", sa.String(256), nullable=True),
        sa.Column("enterprise_verification_sha256", sa.String(64), nullable=True),
        sa.Column("enterprise_verified_at", sa.DateTime(), nullable=True),
        sa.Column("enterprise_verified_by_user_id", sa.Integer(), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("users", column)
    if "ix_users_enterprise_subject_id" not in _indexes():
        op.create_index(
            "ix_users_enterprise_subject_id",
            "users",
            ["enterprise_subject_id"],
        )


def downgrade() -> None:
    if "ix_users_enterprise_subject_id" in _indexes():
        op.drop_index("ix_users_enterprise_subject_id", table_name="users")
    columns = _columns()
    for name in (
        "enterprise_verified_at",
        "enterprise_verified_by_user_id",
        "enterprise_verification_sha256",
        "enterprise_legal_name",
        "enterprise_subject_id",
    ):
        if name in columns:
            op.drop_column("users", name)
