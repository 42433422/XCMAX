"""shipment_etl_import_fingerprints：租户+指纹唯一约束。

Revision ID: 2026_07_24_shipment_etl_fingerprints
Revises: 2026_07_21_workflow_persistence
Create Date: 2026-07-24
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2026_07_24_shipment_etl_fingerprints"
down_revision: str | Sequence[str] | None = "2026_07_21_workflow_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "shipment_etl_import_fingerprints"

_ALEMBIC_VERSION_TABLE = "alembic_version"
_ALEMBIC_VERSION_COLUMN = "version_num"
_ALEMBIC_VERSION_WIDTH = 128


def _widen_alembic_version_num_postgres(bind) -> None:
    """PostgreSQL-only: widen alembic_version.version_num to VARCHAR(128) if shorter.

    The default Alembic schema declares version_num as VARCHAR(32), but this
    migration's revision id ("2026_07_24_shipment_etl_fingerprints") is 36 bytes,
    so fresh PostgreSQL installs fail when Alembic stores it. Idempotent: it no-ops
    when the column already has width >= 128. SQLite and other dialects are untouched.
    """
    if bind.dialect.name != "postgresql":
        return
    row = bind.execute(
        sa.text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = :tbl AND column_name = :col"
        ),
        {"tbl": _ALEMBIC_VERSION_TABLE, "col": _ALEMBIC_VERSION_COLUMN},
    ).first()
    if row is None:
        return
    if row[0] is not None and row[0] >= _ALEMBIC_VERSION_WIDTH:
        return
    bind.execute(
        sa.text(
            f"ALTER TABLE {_ALEMBIC_VERSION_TABLE} "
            f"ALTER COLUMN {_ALEMBIC_VERSION_COLUMN} "
            f"TYPE VARCHAR({_ALEMBIC_VERSION_WIDTH})"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _widen_alembic_version_num_postgres(bind)
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
