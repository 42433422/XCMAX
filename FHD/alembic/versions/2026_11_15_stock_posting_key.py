"""Claim only new document postings; preserve every legacy and fulfillment movement."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_15_stock_posting_key"
down_revision = "2026_11_15_delivery_ref_merge"
branch_labels = None
depends_on = None

_NAME = "uq_inventory_out_business_ref"
_WHERE = (
    "document_posting IS TRUE AND transaction_type = 'out' "
    "AND reference_type IS NOT NULL AND reference_id IS NOT NULL"
)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "document_posting" not in {
        column["name"] for column in inspector.get_columns("inventory_transactions")
    }:
        op.add_column(
            "inventory_transactions",
            sa.Column("document_posting", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    # Also replace the over-broad index in databases that ran the unpublished draft.
    if any(index["name"] == _NAME for index in inspector.get_indexes("inventory_transactions")):
        op.drop_index(_NAME, table_name="inventory_transactions")
    op.create_index(
        _NAME,
        "inventory_transactions",
        ["tenant_id", "product_id", "transaction_type", "reference_type", "reference_id"],
        unique=True,
        sqlite_where=sa.text(_WHERE),
        postgresql_where=sa.text(_WHERE),
    )


def downgrade():
    op.drop_index(_NAME, table_name="inventory_transactions")
    op.drop_column("inventory_transactions", "document_posting")
