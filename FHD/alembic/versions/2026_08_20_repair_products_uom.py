"""Repair products UOM fields for databases stamped past the ERP migration.

Revision ID: 2026_08_20_repair_products_uom
Revises: 2026_08_13_tutorial_v2
Create Date: 2026-08-20

Some legacy desktop databases were stamped at a later revision without having
run the ERP absorption migration.  Those databases can therefore contain a
minimal ``products`` table even though Alembic reports them as current.  This
forward-only repair makes the missing product UOM and replenishment fields
idempotently available without disturbing complete databases.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_08_20_repair_products_uom"
down_revision: str | Sequence[str] | None = "2026_08_13_tutorial_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(bind: sa.Connection, table: str) -> set[str]:
    return {str(row.get("name") or "") for row in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "products" not in tables:
        return

    existing = _column_names(bind, "products")
    columns = (
        sa.Column("base_uom_id", sa.Integer(), nullable=True),
        sa.Column("uom_category", sa.String(), nullable=True, server_default="unit"),
        sa.Column(
            "uom_factor", sa.Numeric(precision=18, scale=6), nullable=True, server_default="1"
        ),
        sa.Column(
            "min_stock", sa.Numeric(precision=18, scale=4), nullable=True, server_default="0"
        ),
        sa.Column(
            "max_stock", sa.Numeric(precision=18, scale=4), nullable=True, server_default="0"
        ),
    )
    missing = [column for column in columns if column.name not in existing]
    if missing:
        with op.batch_alter_table("products", recreate="auto") as batch:
            for column in missing:
                batch.add_column(column)

    inspector = sa.inspect(bind)
    index_names = {str(row.get("name") or "") for row in inspector.get_indexes("products")}
    if "ix_products_base_uom_id" not in index_names:
        op.create_index("ix_products_base_uom_id", "products", ["base_uom_id"])

    if "uom_units" not in tables:
        return
    foreign_keys = inspector.get_foreign_keys("products")
    has_base_uom_fk = any(
        list(row.get("constrained_columns") or []) == ["base_uom_id"]
        and row.get("referred_table") == "uom_units"
        and list(row.get("referred_columns") or []) == ["id"]
        for row in foreign_keys
    )
    if not has_base_uom_fk:
        with op.batch_alter_table("products", recreate="auto") as batch:
            batch.create_foreign_key(
                "fk_products_base_uom_id_uom_units",
                "uom_units",
                ["base_uom_id"],
                ["id"],
            )


def downgrade() -> None:
    """Keep repaired legacy columns; the owning ERP migration remains applied."""
