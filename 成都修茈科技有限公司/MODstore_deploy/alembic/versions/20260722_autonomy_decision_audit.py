"""add append-only MODstore autonomy decision evidence"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260722_autonomy_decision_audit"
down_revision = "20260722_customer_value_receipts"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("autonomy_decision_audit"):
        op.create_table(
            "autonomy_decision_audit",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.String(96), nullable=False),
            sa.Column("record_type", sa.String(32), nullable=False, server_default="decision"),
            sa.Column("action_id", sa.String(192), nullable=False),
            sa.Column("action", sa.String(128), nullable=False, server_default="unknown"),
            sa.Column("decision", sa.String(16), nullable=False, server_default=""),
            sa.Column("policy", sa.String(128), nullable=False, server_default=""),
            sa.Column("risk_level", sa.String(16), nullable=False, server_default="blocked"),
            sa.Column("actor_class", sa.String(32), nullable=False, server_default="unknown"),
            sa.Column("run_id", sa.String(192), nullable=False, server_default=""),
            sa.Column(
                "prohibited_rule_hits_json", sa.Text(), nullable=False, server_default="[]"
            ),
            sa.Column("posthoc_verdict", sa.String(32), nullable=False, server_default=""),
            sa.Column("evidence_ref", sa.String(192), nullable=False, server_default=""),
            sa.Column("source", sa.String(128), nullable=False, server_default=""),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column(
                "recorded_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        for name, columns, unique in (
            ("ix_autonomy_decision_audit_event_id", ["event_id"], True),
            ("ix_autonomy_decision_action_id", ["action_id"], False),
            ("ix_autonomy_decision_occurred_at", ["occurred_at"], False),
            ("ix_autonomy_decision_type_decision", ["record_type", "decision"], False),
            ("ix_autonomy_decision_run_id", ["run_id"], False),
        ):
            op.create_index(name, "autonomy_decision_audit", columns, unique=unique)

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS autonomy_decision_audit_no_update
            BEFORE UPDATE ON autonomy_decision_audit
            BEGIN
              SELECT RAISE(ABORT, 'autonomy_decision_audit is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS autonomy_decision_audit_no_delete
            BEFORE DELETE ON autonomy_decision_audit
            BEGIN
              SELECT RAISE(ABORT, 'autonomy_decision_audit is append-only');
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_autonomy_decision_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'autonomy_decision_audit is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            "DROP TRIGGER IF EXISTS autonomy_decision_audit_no_mutation "
            "ON autonomy_decision_audit"
        )
        op.execute(
            """
            CREATE TRIGGER autonomy_decision_audit_no_mutation
            BEFORE UPDATE OR DELETE ON autonomy_decision_audit
            FOR EACH ROW EXECUTE FUNCTION reject_autonomy_decision_audit_mutation()
            """
        )


def downgrade() -> None:
    if not _table_exists("autonomy_decision_audit"):
        return
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS autonomy_decision_audit_no_mutation "
            "ON autonomy_decision_audit"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_autonomy_decision_audit_mutation()")
    op.drop_table("autonomy_decision_audit")
