"""Enforce known SKU identity while preserving unknown models and original product rows."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_25_erp_sku_key"
down_revision = "2026_11_25_erp_identity_keys"
branch_labels = None
depends_on = None

_NAME = "uq_products_tenant_unit_sku"
_COLUMNS = "tenant_id, trim(coalesce(unit, '')), lower(trim(model_number))"
_WHERE = "tenant_id IS NOT NULL AND model_number IS NOT NULL AND trim(model_number) <> ''"


def upgrade() -> None:
    connection = op.get_bind()
    # Stamped legacy product tables may have undergone the UOM repair while
    # still lacking the original SKU columns. Missing values stay unknown.
    columns = {column["name"] for column in sa.inspect(connection).get_columns("products")}
    for name in ("model_number", "unit"):
        if name not in columns:
            op.add_column("products", sa.Column(name, sa.String(), nullable=True))
    conflict = connection.execute(
        sa.text(
            f"SELECT min(id) AS first_id, count(*) AS n FROM products "
            f"WHERE {_WHERE} GROUP BY {_COLUMNS} HAVING count(*) > 1 LIMIT 1"
        )
    ).mappings().first()
    if conflict is not None:
        raise RuntimeError(
            f"{_NAME}: historical SKU conflict; first row id={conflict['first_id']}, "
            f"count={conflict['n']}. Reconcile specifications and references without deletion."
        )
    connection.execute(sa.text(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_NAME} ON products ({_COLUMNS}) WHERE {_WHERE}"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DROP INDEX IF EXISTS {_NAME}"))
