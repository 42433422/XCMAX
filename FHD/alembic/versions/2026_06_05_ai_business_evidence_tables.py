"""AI 业务证据表：shipment_audit_events + contract_expiry_notifications

Revision ID: 2026_06_05_ai_evidence
Revises: 2026_06_02_tenant_rbac
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "2026_06_05_ai_evidence"
down_revision: Union[str, Sequence[str], None] = "2026_06_02_tenant_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "shipment_audit_events"):
        op.create_table(
            "shipment_audit_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("shipment_id", sa.Integer(), nullable=True),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column("reason", sa.String(512), nullable=True),
            sa.Column("ocr_confidence", sa.Float(), nullable=True),
            sa.Column("source", sa.String(32), server_default="shipment"),
        )
        op.create_index("ix_shipment_audit_events_shipment_id", "shipment_audit_events", ["shipment_id"])
        op.create_index("ix_shipment_audit_events_decision", "shipment_audit_events", ["decision"])

    if not _table_exists(conn, "contract_expiry_notifications"):
        op.create_table(
            "contract_expiry_notifications",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("market_user_id", sa.Integer(), nullable=False),
            sa.Column("end_date", sa.String(16), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(), nullable=False),
            sa.Column("push_status", sa.String(16), nullable=False),
            sa.Column("push_channel", sa.String(32), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_contract_expiry_notifications_market_user_id",
            "contract_expiry_notifications",
            ["market_user_id"],
        )
        op.create_index(
            "ix_contract_expiry_notifications_scheduled_at",
            "contract_expiry_notifications",
            ["scheduled_at"],
        )
        op.create_index(
            "ix_contract_expiry_notifications_push_status",
            "contract_expiry_notifications",
            ["push_status"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "contract_expiry_notifications"):
        op.drop_table("contract_expiry_notifications")
    if _table_exists(conn, "shipment_audit_events"):
        op.drop_table("shipment_audit_events")
