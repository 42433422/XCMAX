"""tenant + roles.tenant_id + data_scopes

Revision ID: 2026_06_02_tenant_rbac
Revises: 2026_05_31_cs_delivery_signoffs
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "2026_06_02_tenant_rbac"
down_revision: Union[str, Sequence[str], None] = "2026_05_31_cs_delivery_signoffs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(256), server_default=""),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        conn.execute(
            text("INSERT INTO tenants (code, name, is_active) VALUES ('default', 'Default Tenant', 1)")
        )

    if not _table_exists(conn, "data_scopes"):
        op.create_table(
            "data_scopes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("scope_json", sa.String(2048), server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        conn.execute(
            text(
                "INSERT INTO data_scopes (tenant_id, resource_type, scope_json) "
                "SELECT id, 'product', '{}' FROM tenants WHERE code = 'default'"
            )
        )

    if not _column_exists(conn, "roles", "tenant_id"):
        op.add_column("roles", sa.Column("tenant_id", sa.Integer(), nullable=True))
        conn.execute(
            text(
                "UPDATE roles SET tenant_id = (SELECT id FROM tenants WHERE code = 'default' LIMIT 1) "
                "WHERE tenant_id IS NULL"
            )
        )

    if not _column_exists(conn, "users", "tenant_id"):
        op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
        conn.execute(
            text(
                "UPDATE users SET tenant_id = (SELECT id FROM tenants WHERE code = 'default' LIMIT 1) "
                "WHERE tenant_id IS NULL"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "users", "tenant_id"):
        op.drop_column("users", "tenant_id")
    if _column_exists(conn, "roles", "tenant_id"):
        op.drop_column("roles", "tenant_id")
    if _table_exists(conn, "data_scopes"):
        op.drop_table("data_scopes")
    if _table_exists(conn, "tenants"):
        op.drop_table("tenants")
