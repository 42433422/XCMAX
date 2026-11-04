"""Join independent ticket ETA and incident ownership migrations without rewriting history."""

revision = "20261020_merge_ticket_incident"
down_revision = ("20261020_customer_ticket_eta", "20261020_incident_ownership")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
