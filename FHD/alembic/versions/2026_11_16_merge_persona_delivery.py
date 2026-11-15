"""收口 delivery 与 persona 两条迁移头"""

revision = "2026_11_16_merge_persona_delivery"
down_revision = ("2026_11_15_delivery_slices_merge", "2026_11_16_persona_account_key")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
