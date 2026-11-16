"""Preserve physical row provenance while allowing independently reviewed slices."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_15_etl_source_slices"
down_revision = "2026_11_11_business_ref_unique"
branch_labels = None
depends_on = None

_TABLE = "etl_run_rows"
_OLD = "uq_etl_run_source_row"
_NEW = "uq_etl_run_source_slice"
_KEY = ["run_id", "source_sheet", "source_row"]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    uniques = {constraint["name"] for constraint in inspector.get_unique_constraints(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "source_slice" not in columns:
            batch.add_column(
                sa.Column("source_slice", sa.Integer(), nullable=False, server_default="0")
            )
        if _OLD in uniques:
            batch.drop_constraint(_OLD, type_="unique")
        if _NEW not in uniques:
            batch.create_unique_constraint(_NEW, [*_KEY, "source_slice"])


def _run_rows_table(inspector) -> str | None:
    names = set(inspector.get_table_names())
    if "elt_run_rows" in names:
        return "elt_run_rows"
    if "etl_run_rows" in names:
        return "etl_run_rows"
    return None


def downgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    table = _run_rows_table(inspector)
    if table is None:
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "source_slice" not in columns:
        return
    # Never delete or merge legitimate reviewed slices to satisfy the old key.
    # Check before any DDL, including on SQLite where DDL can auto-commit.
    if connection.execute(
        sa.text(f"SELECT 1 FROM {table} WHERE source_slice != 0 OR source_slice IS NULL LIMIT 1")
    ).first():
        raise RuntimeError(
            "Cannot downgrade ELT source slices without losing provenance; retain this revision"
        )
    duplicates = connection.execute(
        sa.text(
            f"SELECT 1 FROM {table} GROUP BY run_id, source_sheet, source_row HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicates:
        raise RuntimeError(
            "Cannot downgrade ELT source slices: multiple legitimate rows must be preserved"
        )
    uniques = {constraint["name"] for constraint in inspector.get_unique_constraints(table)}
    with op.batch_alter_table(table) as batch:
        if _NEW in uniques:
            batch.drop_constraint(_NEW, type_="unique")
        if _OLD not in uniques:
            batch.create_unique_constraint(_OLD, _KEY)
        batch.drop_column("source_slice")
