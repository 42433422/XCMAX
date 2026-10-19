"""Store the customer-visible expected completion time for support tickets."""

import sqlalchemy as sa
from alembic import op

revision = "20261020_customer_ticket_eta"
down_revision = "20261019_ticket_submitter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_service_tickets" not in inspector.get_table_names():
        return
    columns = {str(row["name"]) for row in inspector.get_columns("customer_service_tickets")}
    if "expected_completion_at" not in columns:
        op.add_column(
            "customer_service_tickets",
            sa.Column("expected_completion_at", sa.DateTime(), nullable=True),
        )
    indexes = {
        str(row["name"])
        for row in sa.inspect(op.get_bind()).get_indexes("customer_service_tickets")
        if row.get("name")
    }
    if "ix_customer_service_tickets_expected_completion_at" not in indexes:
        op.create_index(
            "ix_customer_service_tickets_expected_completion_at",
            "customer_service_tickets",
            ["expected_completion_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_service_tickets" not in inspector.get_table_names():
        return
    indexes = {
        str(row["name"])
        for row in inspector.get_indexes("customer_service_tickets")
        if row.get("name")
    }
    if "ix_customer_service_tickets_expected_completion_at" in indexes:
        op.drop_index(
            "ix_customer_service_tickets_expected_completion_at",
            table_name="customer_service_tickets",
        )
    columns = {
        str(row["name"])
        for row in sa.inspect(op.get_bind()).get_columns("customer_service_tickets")
    }
    if "expected_completion_at" in columns:
        op.drop_column("customer_service_tickets", "expected_completion_at")
