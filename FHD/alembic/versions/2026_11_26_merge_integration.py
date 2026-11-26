"""Join the Excel export, purchase return and workspace preferences histories."""

revision = "2026_11_26_merge_integration"
down_revision = (
    "2026_11_24_excel_export",
    "2026_11_25_purchase_returns",
    "2026_11_25_workspace_prefs_unique",
)
branch_labels = depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
