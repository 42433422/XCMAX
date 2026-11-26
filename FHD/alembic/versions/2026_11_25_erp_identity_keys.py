"""Enforce tenant supplier names and exact physical stock identities without data loss."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_25_erp_identity_keys"
down_revision = "2026_11_24_trial_session"
branch_labels = None
depends_on = None

# Legacy NULL tenant rows remain quarantined; never guess their ownership.
# Four stock indexes cover every combination of nullable batch and location.
_INDEXES = (
    (
        "uq_supplier_tenant_live_name",
        "suppliers",
        "tenant_id, lower(trim(name))",
        "tenant_id IS NOT NULL AND coalesce(status, '') <> 'deleted'",
    ),
    (
        "uq_stock_identity_batch_location",
        "inventory_ledger",
        "tenant_id, product_id, warehouse_id, batch_no, location_id",
        "tenant_id IS NOT NULL AND batch_no IS NOT NULL AND location_id IS NOT NULL",
    ),
    (
        "uq_stock_identity_batch",
        "inventory_ledger",
        "tenant_id, product_id, warehouse_id, batch_no",
        "tenant_id IS NOT NULL AND batch_no IS NOT NULL AND location_id IS NULL",
    ),
    (
        "uq_stock_identity_location",
        "inventory_ledger",
        "tenant_id, product_id, warehouse_id, location_id",
        "tenant_id IS NOT NULL AND batch_no IS NULL AND location_id IS NOT NULL",
    ),
    (
        "uq_stock_identity_unassigned",
        "inventory_ledger",
        "tenant_id, product_id, warehouse_id",
        "tenant_id IS NOT NULL AND batch_no IS NULL AND location_id IS NULL",
    ),
)


def upgrade() -> None:
    connection = op.get_bind()
    # Check every identity before any schema writes. No automatic merging,
    # reassignment of foreign keys, quantity adjustment or deletion is safe.
    for name, table, columns, where in _INDEXES:
        conflict = connection.execute(sa.text(
            f"SELECT min(id) AS first_id, count(*) AS n FROM {table} "
            f"WHERE {where} GROUP BY {columns} HAVING count(*) > 1 LIMIT 1"
        )).mappings().first()
        if conflict is not None:
            raise RuntimeError(
                f"{name}: historical identity conflict; first row id="
                f"{conflict['first_id']}, count={conflict['n']}. "
                "Reconcile original records and their references before retrying."
            )
    for name, table, columns, where in _INDEXES:
        # Fresh squashed baselines already use current ORM metadata. PostgreSQL
        # and SQLite both support this DDL, including the expression index.
        connection.execute(sa.text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({columns}) WHERE {where}"
        ))


def downgrade() -> None:
    # Schema rollback changes only guards, never historical rows.
    connection = op.get_bind()
    for name, _, _, _ in reversed(_INDEXES):
        connection.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
