"""Separate explicit measurement units from legacy customer labels."""

import sqlalchemy as sa

from alembic import op

revision = "2026_09_09_product_uom"
down_revision = "2026_09_09_customer_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("measurement_unit", sa.String(50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_column("measurement_unit")
