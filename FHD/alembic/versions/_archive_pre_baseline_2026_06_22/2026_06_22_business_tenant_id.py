"""Add tenant_id to core business tables (products, purchase_units).

Revision ID: 2026_06_22_biz_tenant_id
Revises: 2026_06_22_account_tier
Create Date: 2026-06-22

多租户数据隔离作用域：为核心业务表补 nullable tenant_id（其余表后续按同一模式纳入）。
- nullable：存量数据 tenant_id 为 NULL，配合 NULL 容忍过滤不被隐藏。
- 与 init_db.ensure_business_tenant_id_columns 的运行时补列等价。
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "2026_06_22_biz_tenant_id"
down_revision: str | Sequence[str] | None = "2026_06_22_account_tier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "products",
    "purchase_units",
    "materials",
    "shipment_records",
    "financial_transactions",
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "purchase_inbounds",
    "purchase_inbound_items",
    "warehouses",
    "storage_locations",
    "inventory_ledger",
    "inventory_transactions",
)


def _has_table(conn, table: str) -> bool:
    try:
        return table in set(inspect(conn).get_table_names() or [])
    except Exception:
        return False


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
    except Exception:
        return False
    return column in cols


def upgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        if not _has_table(conn, table):
            continue
        if _column_exists(conn, table, "tenant_id"):
            continue
        op.add_column(table, sa.Column("tenant_id", sa.Integer(), nullable=True))
        try:
            op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        if not _column_exists(conn, table, "tenant_id"):
            continue
        try:
            op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        except Exception:
            pass
        op.drop_column(table, "tenant_id")
