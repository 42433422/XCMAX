"""Merge ELT heads and reconcile the run-row schema.

背景：``2026_11_11_business_ref_unique``、``2026_11_11_etl_source_slice`` 与
``2026_11_13_elt_table_rename`` 共用同一个 ``down_revision``，形成三个并行 head。
已装用户的 ``alembic_version`` 停在 rename 之后时，``alembic upgrade head`` 无法
推进，``elt_run_rows`` 缺少 ``source_slice``，ELT 预览写快照时报
``table elt_run_rows has no column named source_slice``。

本迁移做三件事：
1. 把三个 head 合并成一条链；
2. 给 ``elt_run_rows`` 补 ``source_slice``，唯一约束统一为 ``elt`` 命名；
3. 删除改名后遗留且为空的历史 ``etl_*`` 表；若新表尚不存在或为空、旧表仍有
   数据，则收回旧表而不是丢弃（数据尚未在 ``elt_*`` 中）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2026_11_15_elt_schema_reconcile"
down_revision = "2026_11_11_business_ref_unique"
branch_labels = None
depends_on = None

# 先处理子表，再处理父表，避免改名或删除时破坏仍指向旧名的外键。
_LEGACY_TABLES = (
    "etl_archive_assets",
    "etl_archive_versions",
    "etl_archive_quotas",
    "etl_run_rows",
    "etl_target_configs",
    "etl_template_versions",
    "etl_runs",
    "etl_templates",
    "etl_uploads",
)

_SLICE_COLUMNS = ("run_id", "source_sheet", "source_row", "source_slice")
_OLD_UNIQUE = "uq_etl_run_source_row"
_SLICE_UNIQUE_LEGACY = "uq_etl_run_source_slice"
_SLICE_UNIQUE = "uq_elt_run_source_slice"


def _current_name(legacy: str) -> str:
    return "elt_" + legacy[len("etl_") :]


def _row_count(bind, name: str) -> int:
    return int(bind.execute(sa.text(f'SELECT count(*) FROM "{name}"')).scalar() or 0)


def _reclaim_legacy_tables() -> None:
    """只删除已空的历史表；空的新表让位给仍有数据的旧表。"""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    to_rename: list[tuple[str, str]] = []
    to_drop_legacy: list[str] = []
    empty_dest: list[str] = []
    conflicts: list[str] = []
    for name in _LEGACY_TABLES:
        if name not in tables:
            continue
        current = _current_name(name)
        old_count = _row_count(bind, name)
        if current not in tables:
            to_rename.append((name, current))
            continue
        new_count = _row_count(bind, current)
        if old_count == 0:
            to_drop_legacy.append(name)
        elif new_count == 0:
            empty_dest.append(current)
            to_rename.append((name, current))
        else:
            conflicts.append(f"{name}->{current} ({old_count} vs {new_count} rows)")
    if conflicts:
        raise RuntimeError(
            "Cannot drop leftover ETL tables while both names still hold data: "
            + ", ".join(conflicts)
        )
    for dest in empty_dest:
        op.drop_table(dest)
    for old, new in to_rename:
        op.rename_table(old, new)
    for name in to_drop_legacy:
        op.drop_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 之前失败的重建会留下 _alembic_tmp_*，它会让后续 batch 操作永远失败。
    for name in sorted(tables):
        if name.startswith("_alembic_tmp_"):
            op.drop_table(name)

    # 先收回仍有数据的历史表，再改现行 elt_run_rows 的列与约束。
    _reclaim_legacy_tables()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

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


def downgrade() -> None:
    """只还原约束命名与列，不重建历史 etl_* 空表（无数据价值）。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "elt_run_rows" not in set(inspector.get_table_names()):
        return
    uniques = {item["name"] for item in inspector.get_unique_constraints("elt_run_rows")}
    columns = {column["name"] for column in inspector.get_columns("elt_run_rows")}
    if (
        "source_slice" in columns
        and bind.execute(
            sa.text(
                "SELECT 1 FROM elt_run_rows WHERE source_slice != 0 OR source_slice IS NULL LIMIT 1"
            )
        ).first()
    ):
        raise RuntimeError(
            "Cannot downgrade delivery histories without losing ELT slice provenance"
        )
    with op.batch_alter_table("elt_run_rows") as batch:
        if _SLICE_UNIQUE in uniques:
            batch.drop_constraint(_SLICE_UNIQUE, type_="unique")
        if _OLD_UNIQUE not in uniques:
            batch.create_unique_constraint(_OLD_UNIQUE, ["run_id", "source_sheet", "source_row"])
        if "source_slice" in columns:
            batch.drop_column("source_slice")
