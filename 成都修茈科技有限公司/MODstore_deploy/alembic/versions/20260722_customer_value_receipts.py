"""add append-only customer value evidence receipts"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260722_customer_value_receipts"
down_revision = "20260722_outbox_dlq_resolution"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("customer_value_receipts"):
        op.create_table(
            "customer_value_receipts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("receipt_id", sa.String(96), nullable=False),
            sa.Column("receipt_kind", sa.String(32), nullable=False),
            sa.Column(
                "verification_status",
                sa.String(32),
                nullable=False,
                server_default="pending_evidence",
            ),
            sa.Column("customer_ref", sa.String(128), nullable=False, server_default=""),
            sa.Column("customer_goal_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("order_no", sa.String(96), nullable=False, server_default=""),
            sa.Column("artifact_id", sa.String(256), nullable=False, server_default=""),
            sa.Column("acceptance_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
            sa.Column("payment_provider", sa.String(32), nullable=False, server_default=""),
            sa.Column("provider_trade_no", sa.String(128), nullable=False, server_default=""),
            sa.Column(
                "provider_verification", sa.String(64), nullable=False, server_default=""
            ),
            sa.Column("environment", sa.String(32), nullable=False, server_default=""),
            sa.Column("source_event_id", sa.String(192), nullable=False, server_default=""),
            sa.Column("source_employee_id", sa.String(128), nullable=False, server_default=""),
            sa.Column(
                "supersedes_receipt_id", sa.String(96), nullable=False, server_default=""
            ),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("evidence_digest", sa.String(64), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column(
                "recorded_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "ix_customer_value_receipts_receipt_id",
            "customer_value_receipts",
            ["receipt_id"],
            unique=True,
        )
        op.create_index(
            "ix_customer_value_receipts_order_no",
            "customer_value_receipts",
            ["order_no"],
        )
        op.create_index(
            "ix_customer_value_receipts_goal_id",
            "customer_value_receipts",
            ["customer_goal_id"],
        )
        op.create_index(
            "ix_customer_value_receipts_kind_status",
            "customer_value_receipts",
            ["receipt_kind", "verification_status"],
        )
        op.create_index(
            "ix_customer_value_receipts_occurred_at",
            "customer_value_receipts",
            ["occurred_at"],
        )
        op.create_index(
            "ix_customer_value_receipts_source_event_id",
            "customer_value_receipts",
            ["source_event_id"],
        )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS customer_value_receipts_no_update
            BEFORE UPDATE ON customer_value_receipts
            BEGIN
              SELECT RAISE(ABORT, 'customer_value_receipts is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS customer_value_receipts_no_delete
            BEFORE DELETE ON customer_value_receipts
            BEGIN
              SELECT RAISE(ABORT, 'customer_value_receipts is append-only');
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_customer_value_receipt_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'customer_value_receipts is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            "DROP TRIGGER IF EXISTS customer_value_receipts_no_mutation "
            "ON customer_value_receipts"
        )
        op.execute(
            """
            CREATE TRIGGER customer_value_receipts_no_mutation
            BEFORE UPDATE OR DELETE ON customer_value_receipts
            FOR EACH ROW EXECUTE FUNCTION reject_customer_value_receipt_mutation()
            """
        )


def downgrade() -> None:
    if not _table_exists("customer_value_receipts"):
        return
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS customer_value_receipts_no_mutation "
            "ON customer_value_receipts"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_customer_value_receipt_mutation()")
    op.drop_table("customer_value_receipts")
