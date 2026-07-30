"""shipment_etl_import_fingerprints：租户+指纹唯一约束。

Revision ID: 2026_07_24_shipment_etl_fingerprints
Revises: 2026_07_21_workflow_persistence
Create Date: 2026-07-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_24_shipment_etl_fingerprints"
down_revision: Union[str, Sequence[str], None] = "2026_07_21_workflow_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "shipment_etl_import_fingerprints"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_key", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("unit_name", sa.String(length=255), nullable=True),
        sa.Column("order_number", sa.String(length=128), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("source_kind", sa.String(length=64), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_key", "fingerprint", name="uq_shipment_etl_tenant_fingerprint"),
    )
    op.create_index("ix_shipment_etl_fp_tenant_key", _TABLE, ["tenant_key"])
    op.create_index("ix_shipment_etl_fp_fingerprint", _TABLE, ["fingerprint"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return
    op.drop_index("ix_shipment_etl_fp_fingerprint", table_name=_TABLE)
    op.drop_index("ix_shipment_etl_fp_tenant_key", table_name=_TABLE)
    op.drop_table(_TABLE)
