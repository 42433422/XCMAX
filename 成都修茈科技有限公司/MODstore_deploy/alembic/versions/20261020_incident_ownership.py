"""Durable incident inbox and fenced dispatch ownership.

Revision ID: 20261020_incident_ownership
Revises: 20261019_ticket_submitter
"""

import sqlalchemy as sa

from alembic import op

revision = "20261020_incident_ownership"
down_revision = "20261019_ticket_submitter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "incident_inbox" not in tables:
        op.create_table(
            "incident_inbox",
            sa.Column("inbox_key", sa.String(192), primary_key=True),
            sa.Column(
                "incident_event_id",
                sa.Integer(),
                sa.ForeignKey("incident_events.id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "incident_claims" not in tables:
        op.create_table(
            "incident_claims",
            sa.Column(
                "event_id",
                sa.Integer(),
                sa.ForeignKey("incident_events.id"),
                primary_key=True,
            ),
            sa.Column("owner_token", sa.String(64), nullable=False, server_default=""),
            sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lease_until", sa.DateTime(), nullable=False),
            sa.Column(
                "dispatch_state",
                sa.String(16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("last_error", sa.String(512), nullable=False, server_default=""),
        )
        op.create_index("ix_incident_claims_dispatch_state", "incident_claims", ["dispatch_state"])

    if "event_outbox" in tables:
        columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("event_outbox")}
        if "claim_token" not in columns:
            op.add_column(
                "event_outbox",
                sa.Column("claim_token", sa.String(64), nullable=False, server_default=""),
            )
        if "claim_until" not in columns:
            op.add_column("event_outbox", sa.Column("claim_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # These identities prevent duplicate execution. Never erase them on rollback.
    pass
