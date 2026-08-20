#!/usr/bin/env python3
# mypy: disable-error-code="arg-type, attr-defined, union-attr"
"""Schema 漂移门禁：ORM 模型 metadata vs Alembic 迁移链实际建出的 schema。

原理
----
1. 在临时 SQLite 库上执行 ``alembic upgrade head``，得到「迁移链承诺的 schema」。
2. 用 Alembic autogenerate 引擎（``compare_metadata``）对比该库与
   ``Base.metadata``（模型承诺的 schema），diff 方向 = 让库变成模型所需的操作。
3. 有差异 → 退出码 1 并打印缺失/多余的表、列、索引清单；无差异 → 退出码 0。

与 ``alembic check`` 的关系：同一引擎，但本脚本把 diff 渲染成「缺哪张表、
哪一列」的人类可读清单，供本地开发与 CI 观察期使用。CI 权威 parity 门禁见
``.github/workflows/fhd-alembic-ssot.yml``（``alembic upgrade head`` + ``alembic check``）。

治理公约（详见 docs/guides/ALEMBIC_MIGRATION_GUIDE.md「现状与公约」）：
  * 新增模型/字段必须同时提交迁移脚本（本门禁负责拦截只改模型忘写迁移的 PR）；
  * ``app/db/init_db.py`` 的 ``create_all`` 保留为桌面端（SQLite）兜底；
  * 生产 PostgreSQL 以 Alembic 迁移链为 schema 唯一真相源。

用法：
    python scripts/dev/check_schema_drift.py            # 漂移时退出码 1
    python scripts/dev/check_schema_drift.py --keep-db  # 保留临时库便于排查

退出码：0 = 无漂移；1 = 有漂移；2 = 门禁自身执行失败（环境/导入错误）。
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

from app.utils.operational_errors import BOUNDARY_ERRORS

REPO_ROOT = Path(__file__).resolve().parents[2]  # FHD/
sys.path.insert(0, str(REPO_ROOT))

# 与 alembic/env.py 保持一致：这些表由迁移内 raw SQL 创建、刻意无 ORM 模型，
# 不参与 autogenerate 对比。
NON_ORM_TABLES = {
    "templates",
    "template_usage_log",
    "distillation_log",
    "training_stats",
    "excel_vector_chunks",
    "excel_vector_indexes",
}


def _include_name(name: str, type_: str, _parent_names: dict) -> bool:
    if type_ == "table":
        return name not in NON_ORM_TABLES
    return True


def _upgrade_temp_db(db_url: str) -> None:
    """在临时库上把迁移链跑到 head。"""
    os.environ["DATABASE_URL"] = db_url  # alembic/env.py 只认这个变量
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(cfg, "head")


def _produce_upgrade_ops(db_url: str):
    """autogenerate 引擎：迁移链建出的库 vs 模型 metadata。

    返回 (is_empty, ops)：与 ``alembic check`` 同源的 ``produce_migrations``
    结果——check 命令正是以 ``upgrade_ops.is_empty()`` 判定漂移，ops 为展平后
    的 MigrateOperation 列表（含 ModifyTableOps 内嵌子操作）。
    """
    from alembic.autogenerate import produce_migrations
    from alembic.migration import MigrationContext
    from alembic.operations import ops as o
    from sqlalchemy import create_engine

    import app.db.models  # noqa: F401  (populates Base.metadata)
    from app.db.base import Base

    engine = create_engine(db_url)
    with engine.connect() as conn:
        mc = MigrationContext.configure(
            conn,
            opts={
                "target_metadata": Base.metadata,
                "include_name": _include_name,
            },
        )
        script = produce_migrations(mc, Base.metadata)
        upgrade_ops = script.upgrade_ops
        flat: list = []
        for op in upgrade_ops.ops:
            if isinstance(op, o.ModifyTableOps):
                flat.extend(op.ops)
            else:
                flat.append(op)
        return upgrade_ops.is_empty(), flat


def _render(ops: list) -> str:
    """把 MigrateOperation 列表渲染成「缺什么」的人类可读清单。"""
    from alembic.operations import ops as o

    missing_tables: list[str] = []
    extra_tables: list[str] = []
    missing_cols: list[str] = []
    extra_cols: list[str] = []
    indexes: list[str] = []
    col_defs: list[str] = []
    other: list[str] = []

    for op in ops:
        if isinstance(op, o.CreateTableOp):
            missing_tables.append(op.table_name)
        elif isinstance(op, o.DropTableOp):
            extra_tables.append(op.table_name)
        elif isinstance(op, o.AddColumnOp):
            missing_cols.append(f"{op.table_name}.{op.column.name}")
        elif isinstance(op, o.DropColumnOp):
            extra_cols.append(f"{op.table_name}.{op.column_name}")
        elif isinstance(op, o.CreateIndexOp):
            indexes.append(f"缺索引 {op.index_name} ON {op.table_name}({', '.join(op.columns)})")
        elif isinstance(op, o.DropIndexOp):
            indexes.append(f"多余索引 {op.index_name} ON {op.table_name}")
        elif isinstance(
            op,
            (
                o.ModifyColumnTypeOp,
                o.ModifyColumnDefaultOp,
                o.ModifyColumnNullableOp,
                o.ModifyColumnCommentOp,
            ),
        ):
            col_defs.append(f"{op.table_name}.{op.column_name} ({type(op).__name__})")
        else:
            other.append(repr(op))

    sections: list[str] = []
    if missing_tables:
        sections.append(
            "模型已定义但迁移链未建表（缺迁移）:\n"
            + "\n".join(f"    - {t}" for t in sorted(missing_tables))
        )
    if extra_tables:
        sections.append(
            "迁移链建出但模型已删除的表（迁移未回收）:\n"
            + "\n".join(f"    - {t}" for t in sorted(extra_tables))
        )
    if missing_cols:
        sections.append(
            "模型已定义但迁移链未建列（缺迁移）:\n"
            + "\n".join(f"    - {c}" for c in sorted(missing_cols))
        )
    if extra_cols:
        sections.append(
            "迁移链建出但模型已删除的列:\n" + "\n".join(f"    - {c}" for c in sorted(extra_cols))
        )
    if indexes:
        sections.append("索引差异:\n" + "\n".join(f"    - {i}" for i in sorted(indexes)))
    if col_defs:
        sections.append(
            "列定义差异（类型/default/nullable）:\n"
            + "\n".join(f"    - {c}" for c in sorted(col_defs))
        )
    if other:
        sections.append("约束/其他差异:\n" + "\n".join(f"    - {x}" for x in other))
    return "\n\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-db", action="store_true", help="保留临时库便于排查")
    args = parser.parse_args()

    logging.getLogger("alembic").setLevel(logging.WARNING)

    tmpdir = tempfile.mkdtemp(prefix="xcagi_schema_drift_")
    db_url = f"sqlite:///{tmpdir}/drift.db"
    try:
        _upgrade_temp_db(db_url)
        # env.py 的 fileConfig 会重置日志级别；upgrade 输出保留，压住 autogen 插件噪音
        logging.getLogger("alembic").setLevel(logging.WARNING)
        is_empty, ops = _produce_upgrade_ops(db_url)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001 — 门禁自身失败要与「有漂移」区分
        print(f"[schema-drift] 门禁执行失败（非漂移结论）: {exc}")
        return 2
    finally:
        if args.keep_db:
            print(f"[schema-drift] 临时库保留于: {tmpdir}")
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if not is_empty:
        print(f"[schema-drift] FAIL：检测到 {len(ops)} 项模型与迁移链漂移：\n")
        print(_render(ops))
        print(
            "\n修复指引：修改 app/db/models/ 后必须同时提交迁移：\n"
            "    DATABASE_URL=sqlite:////tmp/xcagi_autogen.db alembic stamp head\n"
            "    DATABASE_URL=sqlite:////tmp/xcagi_autogen.db alembic revision --autogenerate -m '<变更说明>'\n"
            "然后人工审查生成的脚本（删噪音、确认无意外 DROP），随模型改动同 PR 提交。"
        )
        return 1
    print("[schema-drift] PASS：模型 metadata 与迁移链 schema 一致，无漂移。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
