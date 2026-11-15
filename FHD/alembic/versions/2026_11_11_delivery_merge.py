"""Join sales permission upgrade and ELT source-slice histories unchanged."""

revision = "2026_11_11_delivery_merge"
down_revision = ("2026_11_11_sales_create_perm", "2026_11_11_etl_source_slice")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
