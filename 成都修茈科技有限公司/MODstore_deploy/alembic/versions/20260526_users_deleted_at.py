"""users.deleted_at for account deletion (app store compliance)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_users_deleted_at"
down_revision = "20260512_consolidate_init_db_columns"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).fetchone()
    return result is not None


def upgrade() -> None:
    if not _col_exists("users", "deleted_at"):
        op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
        op.create_index("ix_users_deleted_at", "users", ["deleted_at"], unique=False)


def downgrade() -> None:
    if _col_exists("users", "deleted_at"):
        op.drop_index("ix_users_deleted_at", table_name="users")
        op.drop_column("users", "deleted_at")
