"""Create data-preserving supplier return documents linked to original receipts.

No historical purchase receipt, inventory, or journal data is rewritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "2026_11_25_purchase_returns"
down_revision = "2026_11_25_erp_sku_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    required = (
        "purchase_inbounds", "purchase_inbound_items", "approval_requests",
        "journal_entries", "products", "suppliers", "warehouses",
    )
    missing = [name for name in required if not inspector.has_table(name)]
    if missing:
        raise RuntimeError(
            "purchase return migration requires original ERP tables: "
            + ", ".join(missing)
        )
    exists_return = inspector.has_table("purchase_returns")
    exists_items = inspector.has_table("purchase_return_items")
    if exists_return != exists_items:
        raise RuntimeError(
            "partial purchase return schema; reconcile before migration, do not drop data"
        )
    if exists_return:
        # Fresh ORM bootstrap already provisioned both; do not rewrite rows.
        return

    op.create_table(
        "purchase_returns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("return_no", sa.String(50), nullable=False),
        sa.Column(
            "approval_request_id", sa.Integer(),
            sa.ForeignKey("approval_requests.id"), nullable=False,
        ),
        sa.Column(
            "inbound_id", sa.Integer(),
            sa.ForeignKey("purchase_inbounds.id"), nullable=False,
        ),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id")),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "return_no", name="uq_purchase_returns_tenant_no"),
        sa.UniqueConstraint(
            "tenant_id", "approval_request_id",
            name="uq_purchase_returns_approved_request",
        ),
        sa.CheckConstraint(
            "total_amount >= 0", name="ck_purchase_return_amount_nonnegative",
        ),
    )
    op.create_index(
        "ix_purchase_returns_tenant_id", "purchase_returns", ["tenant_id"]
    )
    op.create_table(
        "purchase_return_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column(
            "return_id", sa.Integer(),
            sa.ForeignKey("purchase_returns.id"), nullable=False,
        ),
        sa.Column(
            "inbound_item_id", sa.Integer(),
            sa.ForeignKey("purchase_inbound_items.id"), nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("batch_no", sa.String(50)),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("storage_locations.id")),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_return_item_qty_positive"),
        sa.CheckConstraint("amount >= 0", name="ck_purchase_return_item_amount_nonnegative"),
    )
    op.create_index(
        "ix_purchase_return_items_tenant_id", "purchase_return_items", ["tenant_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("purchase_return_items", "purchase_returns"):
        if inspector.has_table(table):
            count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            if count:
                raise RuntimeError(
                    f"refusing to erase {count} posted supplier return records in {table}"
                )
    if inspector.has_table("purchase_return_items"):
        op.drop_index("ix_purchase_return_items_tenant_id", table_name="purchase_return_items")
        op.drop_table("purchase_return_items")
    if inspector.has_table("purchase_returns"):
        op.drop_index("ix_purchase_returns_tenant_id", table_name="purchase_returns")
        op.drop_table("purchase_returns")
