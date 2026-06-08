"""Backfill NULL created_at/updated_at on core business tables.

Revision ID: 2026_06_07_audit_ts
Revises: 2026_06_06_seed_surface_audit_enterprise_demo_user
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op

revision = "2026_06_07_audit_ts"
down_revision = "2026_06_06_surface_audit_demo"
branch_labels = None
depends_on = None

_TABLES = (
    "products",
    "shipments",
    "purchase_orders",
    "inventory_items",
    "materials",
    "users",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            UPDATE {table}
            SET created_at = COALESCE(created_at, NOW() AT TIME ZONE 'UTC'),
                updated_at = COALESCE(updated_at, NOW() AT TIME ZONE 'UTC')
            WHERE created_at IS NULL OR updated_at IS NULL
            """
        )


def downgrade() -> None:
    pass
