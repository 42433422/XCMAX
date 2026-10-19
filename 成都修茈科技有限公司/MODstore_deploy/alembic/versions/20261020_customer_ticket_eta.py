"""Store the customer-visible expected completion time for support tickets."""

import sqlalchemy as sa
from alembic import op

revision = "20261020_customer_ticket_eta"
down_revision = "20261019_ticket_submitter"
branch_labels = None
depends_on = None

_TABLE = "customer_service_tickets"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {str(row["name"]) for row in inspector.get_columns(_TABLE)}
    if "expected_completion_at" not in columns:
        op.add_column(_TABLE, sa.Column("expected_completion_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    columns = {str(row["name"]) for row in inspector.get_columns(_TABLE)}
    if "expected_completion_at" in columns:
        op.drop_column(_TABLE, "expected_completion_at")
