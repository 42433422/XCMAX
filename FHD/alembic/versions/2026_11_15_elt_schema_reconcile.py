"""Merge ELT heads and reconcile the run-row schema.

背景：``2026_11_11_business_ref_unique``、``2026_11_11_etl_source_slice`` 与
``2026_11_13_elt_table_rename`` 共用同一个 ``down_revision``，形成三个并行 head。
已装用户的 ``alembic_version`` 停在 rename 之后时，``alembic upgrade head`` 无法
推进，``elt_run_rows`` 缺少 ``source_slice``，ELT 预览写快照时报
``table elt_run_rows has no column named source_slice``。

本迁移做三件事：
1. 把三个 head 合并成一条链；
2. 给 ``elt_run_rows`` 补 ``source_slice``，唯一约束统一为 ``elt`` 命名；
3. 删除改名后遗留且为空的历史 ``etl_*`` 表（数据已在 ``elt_*`` 中）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2026_11_15_elt_schema_reconcile"
down_revision = "2026_11_11_business_ref_unique"
branch_labels = None
depends_on = None

_LEGACY_TABLES = (
    "etl_archive_assets",
    "etl_archive_quotas",
    "etl_archive_versions",
    "etl_run_rows",
    "etl_runs",
    "etl_target_configs",
    "etl_template_versions",
    "etl_templates",
    "etl_uploads",
)

_SLICE_COLUMNS = ("run_id", "source_sheet", "source_row", "source_slice")
_OLD_UNIQUE = "uq_etl_run_source_row"
_SLICE_UNIQUE_LEGACY = "uq_etl_run_source_slice"
_SLICE_UNIQUE = "uq_elt_run_source_slice"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 之前失败的重建会留下 _alembic_tmp_*，它会让后续 batch 操作永远失败。
    for name in sorted(tables):
        if name.startswith("_alembic_tmp_"):
            op.drop_table(name)

    if "elt_run_rows" in tables:
        columns = {column["name"] for column in inspector.get_columns("elt_run_rows")}
        uniques = {item["name"] for item in inspector.get_unique_constraints("elt_run_rows")}
        indexes = {item["name"] for item in inspector.get_indexes("elt_run_rows")}
        with op.batch_alter_table("elt_run_rows") as batch:
            if "source_slice" not in columns:
                batch.add_column(
                    sa.Column("source_slice", sa.Integer(), nullable=False, server_default="0")
                )
            if _OLD_UNIQUE in uniques:
                batch.drop_constraint(_OLD_UNIQUE, type_="unique")
            elif _OLD_UNIQUE in indexes:
                batch.drop_index(_OLD_UNIQUE)
            if _SLICE_UNIQUE_LEGACY in uniques:
                batch.drop_constraint(_SLICE_UNIQUE_LEGACY, type_="unique")
            if _SLICE_UNIQUE not in uniques:
                batch.create_unique_constraint(_SLICE_UNIQUE, list(_SLICE_COLUMNS))

    for name in _LEGACY_TABLES:
        if name in tables:
            op.drop_table(name)


def downgrade() -> None:
    """只还原约束命名与列，不重建历史 etl_* 空表（无数据价值）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "elt_run_rows" not in set(inspector.get_table_names()):
        return
    uniques = {item["name"] for item in inspector.get_unique_constraints("elt_run_rows")}
    columns = {column["name"] for column in inspector.get_columns("elt_run_rows")}
    with op.batch_alter_table("elt_run_rows") as batch:
        if _SLICE_UNIQUE in uniques:
            batch.drop_constraint(_SLICE_UNIQUE, type_="unique")
        if _OLD_UNIQUE not in uniques:
            batch.create_unique_constraint(_OLD_UNIQUE, ["run_id", "source_sheet", "source_row"])
        if "source_slice" in columns:
            batch.drop_column("source_slice")
