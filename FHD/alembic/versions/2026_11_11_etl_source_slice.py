"""Allow one sheet row to persist as several ELT slices."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_etl_source_slice"
down_revision = "2026_11_11_agent_permissions"
branch_labels = None
depends_on = None


def _names(table: str) -> tuple[set[str], set[str], set[str]]:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    uniques = {item["name"] for item in inspector.get_unique_constraints(table)}
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    return columns, uniques, indexes


def upgrade():
    columns, uniques, indexes = _names("etl_run_rows")
    with op.batch_alter_table("etl_run_rows") as batch:
        if "source_slice" not in columns:
            batch.add_column(
                sa.Column("source_slice", sa.Integer(), nullable=False, server_default="0")
            )
        if "uq_etl_run_source_row" in uniques:
            batch.drop_constraint("uq_etl_run_source_row", type_="unique")
        elif "uq_etl_run_source_row" in indexes:
            batch.drop_index("uq_etl_run_source_row")
        if "uq_etl_run_source_slice" not in uniques:
            batch.create_unique_constraint(
                "uq_etl_run_source_slice",
                ["run_id", "source_sheet", "source_row", "source_slice"],
            )


def downgrade():
    columns, uniques, indexes = _names("etl_run_rows")
    with op.batch_alter_table("etl_run_rows") as batch:
        if "uq_etl_run_source_slice" in uniques:
            batch.drop_constraint("uq_etl_run_source_slice", type_="unique")
        if "uq_etl_run_source_row" not in uniques and "uq_etl_run_source_row" not in indexes:
            batch.create_unique_constraint(
                "uq_etl_run_source_row", ["run_id", "source_sheet", "source_row"]
            )
        if "source_slice" in columns:
            batch.drop_column("source_slice")
