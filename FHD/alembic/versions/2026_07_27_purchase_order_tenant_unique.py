"""Scope purchase order numbers to one tenant.

Revision ID: 2026_07_27_po_tenant_unique
Revises: 2026_07_26_general_etl_v1
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_07_27_po_tenant_unique"
down_revision: str | Sequence[str] | None = "2026_07_26_general_etl_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "purchase_orders"
_TENANT_UNIQUE = "uq_purchase_orders_tenant_order_no"


def _order_number_uniques(bind) -> list[str]:
    if _TABLE not in sa.inspect(bind).get_table_names():
        return []
    names = []
    for item in sa.inspect(bind).get_unique_constraints(_TABLE):
        if item.get("column_names") != ["order_no"]:
            continue
        names.append(str(item.get("name") or "uq_purchase_orders_order_no"))
    return names


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    existing = {
        tuple(item.get("column_names") or ())
        for item in sa.inspect(bind).get_unique_constraints(_TABLE)
    }
    if ("tenant_id", "order_no") in existing:
        return
    with op.batch_alter_table(
        _TABLE,
        recreate="auto",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch_op:
        for constraint_name in _order_number_uniques(bind):
            batch_op.drop_constraint(constraint_name, type_="unique")
        batch_op.create_unique_constraint(_TENANT_UNIQUE, ["tenant_id", "order_no"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table(
        _TABLE,
        recreate="auto",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch_op:
        batch_op.drop_constraint(_TENANT_UNIQUE, type_="unique")
        batch_op.create_unique_constraint("uq_purchase_orders_order_no", ["order_no"])
