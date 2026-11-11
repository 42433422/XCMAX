"""Unique business-document keys for stock-out and financial postings."""

from alembic import op

revision = "2026_11_11_business_ref_unique"
down_revision = "2026_11_11_agent_permissions"
branch_labels = None
depends_on = None

_FIN_WHERE = "reference_type IS NOT NULL AND reference_id IS NOT NULL"
_STOCK_WHERE = (
    "transaction_type = 'out' AND reference_type IS NOT NULL AND reference_id IS NOT NULL"
)


def upgrade():
    op.create_index(
        "uq_fin_txn_business_ref",
        "financial_transactions",
        ["tenant_id", "transaction_type", "reference_type", "reference_id"],
        unique=True,
        postgresql_where=_FIN_WHERE,
        sqlite_where=_FIN_WHERE,
    )
    op.create_index(
        "uq_inventory_out_business_ref",
        "inventory_transactions",
        ["tenant_id", "product_id", "transaction_type", "reference_type", "reference_id"],
        unique=True,
        postgresql_where=_STOCK_WHERE,
        sqlite_where=_STOCK_WHERE,
    )


def downgrade():
    op.drop_index("uq_inventory_out_business_ref", table_name="inventory_transactions")
    op.drop_index("uq_fin_txn_business_ref", table_name="financial_transactions")
