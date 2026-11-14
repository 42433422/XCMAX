"""Join delivery and business-reference histories without replaying schema changes."""

revision = "2026_11_15_delivery_ref_merge"
down_revision = ("2026_11_11_delivery_merge", "2026_11_11_business_ref_unique")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
