"""Allow one sheet row to persist as several ELT slices."""

import sqlalchemy as sa

from alembic import op

revision = "2026_11_11_etl_source_slice"
# 原本与改名迁移并列，形成多 head 导致 upgrade 卡死；改为接在改名之后，保证表名已是 elt_run_rows。
down_revision = "2026_11_13_elt_table_rename"
branch_labels = None
depends_on = None


def _run_rows_table() -> str | None:
    """取当前的运行行表名：改名迁移跑过就是 elt_run_rows，否则用历史名。"""
    names = set(sa.inspect(op.get_bind()).get_table_names())
    if "elt_run_rows" in names:
        return "elt_run_rows"
    if "etl_run_rows" in names:
        return "etl_run_rows"
    return None


def _names(table: str) -> tuple[set[str], set[str], set[str]]:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    uniques = {item["name"] for item in inspector.get_unique_constraints(table)}
    indexes = {item["name"] for item in inspector.get_indexes(table)}
    return columns, uniques, indexes


def upgrade():
    table = _run_rows_table()
    if table is None:
        return
    columns, uniques, indexes = _names(table)
    with op.batch_alter_table(table) as batch:
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
    table = _run_rows_table()
    if table is None:
        return
    columns, uniques, indexes = _names(table)
    with op.batch_alter_table(table) as batch:
        if "uq_etl_run_source_slice" in uniques:
            batch.drop_constraint("uq_etl_run_source_slice", type_="unique")
        if "uq_etl_run_source_row" not in uniques and "uq_etl_run_source_row" not in indexes:
            batch.create_unique_constraint(
                "uq_etl_run_source_row", ["run_id", "source_sheet", "source_row"]
            )
        if "source_slice" in columns:
            batch.drop_column("source_slice")
