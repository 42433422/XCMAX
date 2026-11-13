"""Rename ETL-era database objects to ELT names.

Revision identifiers are intentionally unchanged: they are the immutable
upgrade keys of existing installations. This migration only renames physical
objects (tables, indexes, permission rows and stored upload paths) so code,
data and history stay consistent.

SQLite cannot rename a table-level UNIQUE constraint; on SQLite those keep
their original names while PostgreSQL renames them. Indexes are renamed on
both backends.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2026_11_13_elt_table_rename"
down_revision = "2026_11_11_agent_permissions"
branch_labels = None
depends_on = None

TABLE_PAIRS = (
    ("etl_uploads", "elt_uploads"),
    ("etl_templates", "elt_templates"),
    ("etl_template_versions", "elt_template_versions"),
    ("etl_runs", "elt_runs"),
    ("etl_run_rows", "elt_run_rows"),
    ("etl_target_configs", "elt_target_configs"),
    ("etl_archive_quotas", "elt_archive_quotas"),
    ("etl_archive_assets", "elt_archive_assets"),
    ("etl_archive_versions", "elt_archive_versions"),
    ("etl_price_dimensions", "elt_price_dimensions"),
    ("shipment_etl_import_fingerprints", "shipment_elt_import_fingerprints"),
    ("etl_owned_source", "elt_owned_source"),
    ("etl_database_generation", "elt_database_generation"),
    ("etl_generation_observations", "elt_generation_observations"),
)


def _rename_indexes(bind, table: str) -> None:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return
    for index in inspector.get_indexes(table):
        name = str(index.get("name") or "")
        new_name = name.replace("_etl_", "_elt_")
        if not name or new_name == name:
            continue
        dialect = bind.dialect.name
        if dialect == "postgresql":
            op.execute(f'ALTER INDEX "{name}" RENAME TO "{new_name}"')
        else:
            op.drop_index(name, table_name=table)
            op.create_index(
                new_name,
                table,
                list(index.get("column_names") or []),
                unique=bool(index.get("unique")),
            )


def _rename_unique_constraints(bind, table: str) -> None:
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return
    for constraint in inspector.get_unique_constraints(table):
        name = str(constraint.get("name") or "")
        new_name = name.replace("_etl_", "_elt_")
        if not name or new_name == name:
            continue
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{name}" TO "{new_name}"')


def _rename_tables(pairs) -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for old, new in pairs:
        if old in tables and new not in tables:
            op.rename_table(old, new)


def _rename_permissions(bind) -> None:
    inspector = sa.inspect(bind)
    if "permissions" not in inspector.get_table_names():
        return
    op.execute("UPDATE permissions SET code = replace(code, 'etl.', 'elt.') WHERE code LIKE 'etl.%'")
    op.execute("UPDATE permissions SET module = 'elt' WHERE module = 'etl'")


def upgrade() -> None:
    bind = op.get_bind()
    _rename_tables(TABLE_PAIRS)
    for _old, new in TABLE_PAIRS:
        _rename_indexes(bind, new)
        _rename_unique_constraints(bind, new)
    _rename_permissions(bind)
    tables = set(sa.inspect(bind).get_table_names())
    if "elt_uploads" in tables:
        op.execute(
            "UPDATE elt_uploads SET storage_path = replace(storage_path, '/etl/uploads/', '/elt/uploads/')"
        )
        op.execute(
            "UPDATE elt_uploads SET relative_path = replace(relative_path, 'etl/uploads', 'elt/uploads')"
        )
    if "elt_archive_versions" in tables:
        op.execute(
            "UPDATE elt_archive_versions SET storage_path = replace(storage_path, '/etl/archive/', '/elt/archive/')"
        )


def downgrade() -> None:
    bind = op.get_bind()
    _rename_tables(tuple((new, old) for old, new in TABLE_PAIRS))
    for old, _new in TABLE_PAIRS:
        _rename_indexes(bind, old)
        _rename_unique_constraints(bind, old)
    inspector = sa.inspect(bind)
    if "permissions" in inspector.get_table_names():
        op.execute("UPDATE permissions SET code = replace(code, 'elt.', 'etl.') WHERE code LIKE 'elt.%'")
        op.execute("UPDATE permissions SET module = 'etl' WHERE module = 'elt'")
