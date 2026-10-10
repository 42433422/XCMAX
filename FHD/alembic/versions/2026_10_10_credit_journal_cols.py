"""Repair ORM-only columns missing from upgraded desktop databases.

Revision ID: 2026_10_10_credit_journal_cols
Revises: 2026_09_27_tenant_rbac_owner
Create Date: 2026-10-10

The squashed baseline builds tables with ``create_all(checkfirst=True)``, which
never alters a table that already exists.  Databases upgraded from releases that
predate the baseline therefore reach head without columns that fresh installs
receive from the ORM:

* ``customers.credit_limit`` / ``credit_used`` / ``is_credit_limited`` (only
  added by an archived pre-baseline migration);
* ``financial_transactions.journal_entry_id`` (never added by any migration).

On such databases the sales closed-loop approval fails with 409 and the finance
receivables / transactions APIs return 500 (Windows U8 acceptance, 2026-10-10).
This forward-only repair inspects the live schema and adds only what is missing,
so complete databases are untouched and re-running it is a no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_10_10_credit_journal_cols"
down_revision: str | Sequence[str] | None = "2026_09_27_tenant_rbac_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _repair_columns() -> dict[str, tuple[sa.Column, ...]]:
    """Columns mirror app/db/models/customer.py and app/db/models/finance.py."""
    return {
        "customers": (
            sa.Column(
                "credit_limit", sa.Numeric(precision=18, scale=2), nullable=True, server_default="0"
            ),
            sa.Column(
                "credit_used", sa.Numeric(precision=18, scale=2), nullable=True, server_default="0"
            ),
            sa.Column("is_credit_limited", sa.Integer(), nullable=False, server_default="0"),
        ),
        "financial_transactions": (sa.Column("journal_entry_id", sa.Integer(), nullable=True),),
    }


_REPAIR_INDEXES = (
    ("ix_financial_transactions_journal_entry_id", "financial_transactions", "journal_entry_id"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, columns in _repair_columns().items():
        if table not in tables:
            continue
        existing = {str(row.get("name") or "") for row in inspector.get_columns(table)}
        missing = [column for column in columns if column.name not in existing]
        if missing:
            with op.batch_alter_table(table, recreate="auto") as batch:
                for column in missing:
                    batch.add_column(column)

    inspector = sa.inspect(bind)
    for index_name, table, column_name in _REPAIR_INDEXES:
        if table not in tables:
            continue
        indexed = {str(row.get("name") or "") for row in inspector.get_indexes(table)}
        if index_name not in indexed:
            op.create_index(index_name, table, [column_name])


def downgrade() -> None:
    """Keep repaired columns; fresh installs own them through the ORM baseline."""
