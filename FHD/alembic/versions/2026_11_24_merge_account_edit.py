"""Join the account-license and durable edit-proposal migration histories."""

revision = "2026_11_24_merge_account_edit"
down_revision = ("2026_11_24_account_license", "2026_11_24_code_edit_proposals")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # Both original revisions retain their own schema and rollback protections.
    pass
