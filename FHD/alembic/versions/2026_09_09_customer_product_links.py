"""Add explicit customer product associations without rewriting legacy units."""

import sqlalchemy as sa

from alembic import op

revision = "2026_09_09_customer_links"
down_revision = "2026_09_08_wechat_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_product_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column(
            "purchase_unit_id", sa.Integer(), sa.ForeignKey("purchase_units.id"), nullable=False
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "purchase_unit_id", "product_id", name="uq_customer_product_link"
        ),
    )
    op.create_index("ix_customer_product_links_tenant_id", "customer_product_links", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("customer_product_links")
