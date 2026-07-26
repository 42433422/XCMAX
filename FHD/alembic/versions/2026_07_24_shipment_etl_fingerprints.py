"""shipment_etl_import_fingerprints：租户+指纹唯一约束。

Revision ID: 2026_07_24_shipment_etl_fingerprints
Revises: 2026_07_21_workflow_persistence
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_07_24_shipment_etl_fingerprints"
down_revision: str | Sequence[str] | None = "2026_07_21_workflow_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "shipment_etl_import_fingerprints"


def upgrade() -> None:
    bind = op.get_bind()
    # Alembic creates version_num as VARCHAR(32), but this revision ID is 36
    # characters. PostgreSQL enforces that limit while SQLite does not, so widen
    # the migration-owned version column before Alembic records this revision.
    # Keep this before the table-exists early return: older runtimes may already
    # have created the fingerprint table outside Alembic.
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
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
