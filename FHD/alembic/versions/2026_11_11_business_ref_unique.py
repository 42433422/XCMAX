"""Unique business-document keys for stock-out and financial postings."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_business_ref_unique"
down_revision = "2026_11_11_agent_permissions"
branch_labels = None
depends_on = None

_FIN_WHERE = "reference_type IS NOT NULL AND reference_id IS NOT NULL"
_STOCK_WHERE = (
    "transaction_type = 'out' AND reference_type IS NOT NULL AND reference_id IS NOT NULL"
)


def _has_index(table: str, name: str) -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes(table)
    return any(item["name"] == name for item in indexes)


def upgrade():
    if not _has_index("financial_transactions", "uq_fin_txn_business_ref"):
        op.create_index(
            "uq_fin_txn_business_ref",
            "financial_transactions",
            ["tenant_id", "transaction_type", "reference_type", "reference_id"],
            unique=True,
            postgresql_where=sa.text(_FIN_WHERE),
            sqlite_where=sa.text(_FIN_WHERE),
        )
    if not _has_index("inventory_transactions", "uq_inventory_out_business_ref"):
        op.create_index(
            "uq_inventory_out_business_ref",
            "inventory_transactions",
            ["tenant_id", "product_id", "transaction_type", "reference_type", "reference_id"],
            unique=True,
            postgresql_where=sa.text(_STOCK_WHERE),
            sqlite_where=sa.text(_STOCK_WHERE),
        )


def downgrade():
    op.drop_index("uq_inventory_out_business_ref", table_name="inventory_transactions")
    op.drop_index("uq_fin_txn_business_ref", table_name="financial_transactions")
