"""Independent notification read state and recipient binding."""

from alembic import op
import sqlalchemy as sa

revision = "2026_11_25_notification_read"
down_revision = "2026_11_24_trial_session"
branch_labels = None
depends_on = None

_TABLE = "mobile_notification_outbox"


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    if "recipient_scope" not in columns:
        op.add_column(_TABLE, sa.Column("recipient_scope", sa.String(64), nullable=False, server_default=""))
    if "read_at" not in columns:
        op.add_column(_TABLE, sa.Column("read_at", sa.DateTime(), nullable=True))
    # Historical delivery is not a read receipt. Do not guess an old tenant.


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "read_at" in columns:
            batch.drop_column("read_at")
        if "recipient_scope" in columns:
            batch.drop_column("recipient_scope")
