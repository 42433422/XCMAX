"""
XCAGI 数据库路径与初始化入口（应用内）。

目标：
- 让 app/* 不再依赖仓库根目录 db.py
- 兼容 PyInstaller（_MEIPASS）与开发环境
- 支持从 resources/db_seed 复制初始 sqlite
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
import json
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Sequence

from app.utils.external_sqlite import sqlite_conn

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
from app.utils.path_utils import get_app_data_dir, get_base_dir, get_resource_path

logger = logging.getLogger(__name__)


DEFAULT_DB_FILES: tuple[str, ...] = (
    "products.db",
    "inventory.db",
    "voice_learning.db",
    "error_collection.db",
)


def _iter_seed_dirs() -> Iterable[str]:
    """
    返回可能的种子 db 来源目录（按优先级）。
    - resources/db_seed（推荐）
    - base_dir（兼容旧行为）
    - _MEIPASS（打包时解包目录）
    """
    yield get_resource_path("db_seed")
    yield get_base_dir()
    if hasattr(sys, "_MEIPASS"):
        yield sys._MEIPASS  # type: ignore[attr-defined]


def initialize_databases(db_files: Iterable[str] = DEFAULT_DB_FILES) -> None:
    """
    初始化数据库文件（主要用于首次运行/打包环境）。
    规则：如果目标目录已存在同名 db，则不覆盖。
    """
    work_dir = get_app_data_dir()
    os.makedirs(work_dir, exist_ok=True)

    for db_file in db_files:
        target_path = os.path.join(work_dir, db_file)
        if os.path.exists(target_path):
            continue

        source_path = None
        for seed_dir in _iter_seed_dirs():
            cand = os.path.join(seed_dir, db_file)
            if os.path.exists(cand):
                source_path = cand
                break

        if not source_path:
            logger.warning("未找到种子数据库文件：%s（将由 ORM/运行时创建）", db_file)
            continue

        try:
            shutil.copy2(source_path, target_path)
            # 轻量检查
            with sqlite_conn(target_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                _ = cur.fetchall()
        except Exception as e:
            logger.warning("复制数据库失败 %s -> %s: %s", source_path, target_path, e)


def ensure_sqlite_per_mod_database_copies(
    mod_ids: Sequence[str],
    db_files: Iterable[str] = DEFAULT_DB_FILES,
) -> None:
    """
    为每个扩展从「母库」复制出带 Mod 后缀的 SQLite 文件（若目标尚不存在）。

    母库即数据目录下无后缀的 ``products.db`` 等（由 ``initialize_databases`` 从
    ``resources/db_seed`` 首次复制而来）。这样 ``DATABASE_URL`` 按请求头改写为
    ``products__<mod>.db`` 时，各包有独立文件，不会在空文件上直接建表导致与母库「串数据」。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

    work_dir = get_app_data_dir()
    os.makedirs(work_dir, exist_ok=True)
    seen: set[str] = set()
    for raw_id in mod_ids:
        mod_id = str(raw_id or "").strip()
        if not mod_id or mod_id in seen:
            continue
        seen.add(mod_id)
        for db_name in db_files:
            base_path = os.path.join(work_dir, db_name)
            dest_name = sqlite_filename_with_mod_suffix(db_name, mod_id)
            dest_path = os.path.join(work_dir, dest_name)
            if dest_name == db_name or os.path.exists(dest_path):
                continue
            if not os.path.exists(base_path):
                logger.warning(
                    "无法为 Mod %s 准备专用库：母库不存在 %s（跳过 %s）",
                    mod_id,
                    base_path,
                    dest_name,
                )
                continue
            try:
                shutil.copy2(base_path, dest_path)
                logger.info("已为 Mod %s 从母库复制专用 SQLite：%s", mod_id, dest_name)
            except Exception as e:
                logger.warning(
                    "复制 Mod 专用库失败 mod=%s %s -> %s: %s",
                    mod_id,
                    base_path,
                    dest_path,
                    e,
                )


def build_mod_database_seed_plan() -> Dict[str, Any]:
    """
    供设置页 ``/api/system/test-db/status`` 展示：各扩展对应的 SQLite 文件路径与说明。
    与 manifest 可选字段 ``database.seed_files`` / ``database.notes_zh`` 对齐（若存在）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

    work_dir = get_app_data_dir()
    architecture_note_zh = (
        "SQLite：先有母库（如 products.db，来自 resources/db_seed），"
        "每个扩展使用独立文件名（如 products__<mod>.db）；"
        "启动时若专用文件不存在，会从母库复制一份作为初始种子，之后各包数据互不影响。"
        "PostgreSQL 默认仍共用 DATABASE_URL 中的库；需要一包一库时请设置 "
        "XCAGI_MOD_ISOLATED_DATABASES=1 或为各包配置 XCAGI_MOD_DATABASE_URL_*。"
    )
    mods_out: List[Dict[str, Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        metas = mm.list_loaded_mods() or mm.scan_mods()
    except Exception:
        metas = []

    for m in metas:
        mid = str(getattr(m, "id", "") or "").strip()
        if not mid:
            continue
        notes = ""
        extra_seeds: List[Dict[str, str]] = []
        mod_path = str(getattr(m, "mod_path", "") or "").strip()
        if mod_path:
            man = os.path.join(mod_path, "manifest.json")
            if os.path.isfile(man):
                try:
                    with open(man, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    db = data.get("database") if isinstance(data.get("database"), dict) else {}
                    notes = str(db.get("notes_zh") or data.get("database_notes_zh") or "").strip()
                    raw_files = db.get("seed_files") or data.get("database_seed_files") or []
                    if isinstance(raw_files, list):
                        for rel in raw_files:
                            rp = str(rel or "").strip()
                            if not rp:
                                continue
                            ap = os.path.normpath(os.path.join(mod_path, rp))
                            extra_seeds.append({"path": ap})
                    raw_sql = db.get("seed_sql") or data.get("database_seed_sql")
                    if raw_sql:
                        sp = os.path.normpath(os.path.join(mod_path, str(raw_sql).strip()))
                        if os.path.isfile(sp):
                            extra_seeds.append({"path": sp})
                except Exception:
                    pass

        seeds: List[Dict[str, str]] = [
            {"path": os.path.join(work_dir, "products.db"), "role": "sqlite_mother_products"},
            {
                "path": os.path.join(
                    work_dir, sqlite_filename_with_mod_suffix("products.db", mid)
                ),
                "role": "sqlite_per_mod_products",
            },
        ]
        seeds.extend(extra_seeds)
        mods_out.append(
            {
                "mod_id": mid,
                "database_notes": notes,
                "seeds": seeds,
            }
        )

    return {"architecture_note_zh": architecture_note_zh, "mods": mods_out}


def get_db_path(db_name: str = "products.db") -> str:
    """
    获取主数据库（或指定 db）路径。

    当请求上下文存在 ``X-XCAGI-Active-Mod-Id``（SQLite 场景）时，与 ORM 的
    ``DATABASE_URL`` 改写一致，使用带 Mod 后缀的文件名（如 ``products__taiyangniao_pro.db``）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix
    from app.request_active_mod_ctx import get_request_active_mod_id

    mod_id = get_request_active_mod_id()
    fname = sqlite_filename_with_mod_suffix(db_name, mod_id) if mod_id else db_name
    return os.path.join(get_app_data_dir(), fname)


def get_distillation_db_path() -> str:
    return get_db_path("distillation.db")


def init_wechat_tasks_table(db_path: str | None = None) -> None:
    """初始化 wechat_tasks 表（存放从微信解析出来的任务）"""
    db_path = db_path or get_db_path("products.db")
    with sqlite_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wechat_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER,
                username TEXT,
                display_name TEXT,
                message_id TEXT,
                msg_timestamp INTEGER,
                raw_text TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'pending',
                last_status_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_wechat_tasks_contact_status
            ON wechat_tasks (contact_id, status)
            """
        )

        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wechat_tasks_msg_unique
            ON wechat_tasks (message_id, username)
            """
        )

        conn.commit()


def init_distillation_tables(engine: "Engine") -> None:
    """
    在主库上创建蒸馏样本表 distillation_log / training_stats。
    与 SessionLocal 使用同一引擎，避免切换 SQLite/PostgreSQL 后路由与采集脚本连库不一致。
    """
    from sqlalchemy import text

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS distillation_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        slots TEXT,
                        confidence REAL DEFAULT 1.0,
                        source TEXT DEFAULT 'manual',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        used_for_training INTEGER DEFAULT 0
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS training_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        intent TEXT NOT NULL,
                        count INTEGER DEFAULT 0,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            # PostgreSQL 等与 Alembic b1f4a6d2e8c1 一致
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS distillation_log (
                        id BIGSERIAL PRIMARY KEY,
                        query TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        slots TEXT,
                        confidence DOUBLE PRECISION DEFAULT 1.0,
                        source TEXT DEFAULT 'manual',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        used_for_training INTEGER DEFAULT 0
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS training_stats (
                        id BIGSERIAL PRIMARY KEY,
                        intent TEXT NOT NULL,
                        count INTEGER DEFAULT 0,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_intent ON distillation_log(intent)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_used ON distillation_log(used_for_training)"))


def init_extract_logs_tables(engine: "Engine") -> None:
    """
    在主库上创建 extract_logs（与 SessionLocal / pytest 临时 SQLite 使用同一引擎）。
    ExtractLog 仓储使用原生 SQL，需显式建表。
    """
    from sqlalchemy import text

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS extract_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_name TEXT,
                        file_path TEXT,
                        data_type TEXT,
                        total_rows INTEGER DEFAULT 0,
                        valid_rows INTEGER,
                        imported_rows INTEGER,
                        skipped_rows INTEGER,
                        failed_rows INTEGER,
                        status TEXT DEFAULT 'pending',
                        error_message TEXT,
                        field_mapping TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS extract_logs (
                        id BIGSERIAL PRIMARY KEY,
                        file_name TEXT,
                        file_path TEXT,
                        data_type TEXT,
                        total_rows INTEGER DEFAULT 0,
                        valid_rows INTEGER,
                        imported_rows INTEGER,
                        skipped_rows INTEGER,
                        failed_rows INTEGER,
                        status TEXT DEFAULT 'pending',
                        error_message TEXT,
                        field_mapping TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )


def init_template_tables(db_path: str | None = None) -> None:
    """
    初始化模板相关表：
    - templates
    - template_usage_log

    兼容策略：
    - 表不存在时创建
    - 表已存在但缺少新字段时自动补齐
    """
    db_path = db_path or get_db_path("products.db")
    with sqlite_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_key TEXT,
                template_name TEXT NOT NULL,
                template_type TEXT,
                original_file_path TEXT,
                analyzed_data TEXT,
                editable_config TEXT,
                zone_config TEXT,
                merged_cells_config TEXT,
                style_config TEXT,
                business_rules TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS template_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_templates_type_active
            ON templates (template_type, is_active)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id
            ON template_usage_log (template_id)
            """
        )

        # 旧库兼容：若历史 versions 缺少字段，则补齐
        cur.execute("PRAGMA table_info(templates)")
        templates_columns = {str(row[1]).strip() for row in (cur.fetchall() or [])}
        required_templates_columns = {
            "template_key": "ALTER TABLE templates ADD COLUMN template_key TEXT",
            "template_name": "ALTER TABLE templates ADD COLUMN template_name TEXT",
            "template_type": "ALTER TABLE templates ADD COLUMN template_type TEXT",
            "original_file_path": "ALTER TABLE templates ADD COLUMN original_file_path TEXT",
            "analyzed_data": "ALTER TABLE templates ADD COLUMN analyzed_data TEXT",
            "editable_config": "ALTER TABLE templates ADD COLUMN editable_config TEXT",
            "zone_config": "ALTER TABLE templates ADD COLUMN zone_config TEXT",
            "merged_cells_config": "ALTER TABLE templates ADD COLUMN merged_cells_config TEXT",
            "style_config": "ALTER TABLE templates ADD COLUMN style_config TEXT",
            "business_rules": "ALTER TABLE templates ADD COLUMN business_rules TEXT",
            "is_active": "ALTER TABLE templates ADD COLUMN is_active INTEGER DEFAULT 1",
            "created_at": "ALTER TABLE templates ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, sql in required_templates_columns.items():
            if column_name not in templates_columns:
                cur.execute(sql)

        cur.execute("PRAGMA table_info(template_usage_log)")
        usage_columns = {str(row[1]).strip() for row in (cur.fetchall() or [])}
        required_usage_columns = {
            "template_id": "ALTER TABLE template_usage_log ADD COLUMN template_id INTEGER",
            "action": "ALTER TABLE template_usage_log ADD COLUMN action TEXT",
            "result": "ALTER TABLE template_usage_log ADD COLUMN result TEXT",
            "created_at": "ALTER TABLE template_usage_log ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, sql in required_usage_columns.items():
            if column_name not in usage_columns:
                cur.execute(sql)

        conn.commit()


def init_template_tables_for_engine(engine: "Engine") -> None:
    """
    在主库（PostgreSQL）上创建 templates / template_usage_log。
    与 Alembic f0c2a8e1_templates 对齐；启动时幂等补齐，便于未跑迁移的环境。
    """
    from sqlalchemy import inspect, text

    if engine.dialect.name != "postgresql":
        return

    insp = inspect(engine)
    existing = set(insp.get_table_names())

    with engine.begin() as conn:
        if "templates" not in existing:
            conn.execute(
                text(
                    """
                    CREATE TABLE templates (
                        id BIGSERIAL PRIMARY KEY,
                        template_key TEXT,
                        template_name TEXT NOT NULL,
                        template_type TEXT,
                        original_file_path TEXT,
                        analyzed_data TEXT,
                        editable_config TEXT,
                        zone_config TEXT,
                        merged_cells_config TEXT,
                        style_config TEXT,
                        business_rules TEXT,
                        is_active INTEGER DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        if "template_usage_log" not in existing:
            conn.execute(
                text(
                    """
                    CREATE TABLE template_usage_log (
                        id BIGSERIAL PRIMARY KEY,
                        template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
                        action TEXT NOT NULL,
                        result TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_templates_type_active ON templates (template_type, is_active)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id ON template_usage_log (template_id)"
            )
        )


def init_approval_tables(engine: "Engine") -> None:
    """
    在主库上创建审批流相关表（approval_flows / approval_flow_nodes /
    approval_requests / approval_records / approval_delegations）。

    与 Alembic `xcagi_v5_approval_system` 对齐；启动时幂等补齐，便于未跑迁移的环境。
    同时确保 `approval_flows.business_type` 列存在（旧库可能缺失）。
    """
    from sqlalchemy import inspect, text

    from app.db.base import Base
    from app.db.models.approval import (  # noqa: F401
        ApprovalDelegation,
        ApprovalFlow,
        ApprovalFlowNode,
        ApprovalRecord,
        ApprovalRequest,
    )

    target_tables = [
        ApprovalFlow.__table__,
        ApprovalFlowNode.__table__,
        ApprovalRequest.__table__,
        ApprovalRecord.__table__,
        ApprovalDelegation.__table__,
    ]

    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine

        real_engine = _get_real_engine()
    except Exception:
        pass

    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
    except Exception as exc:
        logger.warning("approval 表 create_all 失败（继续尝试 ALTER 兼容）：%s", exc)

    try:
        insp = inspect(real_engine)
        if "approval_flows" in set(insp.get_table_names() or []):
            cols = {c["name"] for c in insp.get_columns("approval_flows")}
            if "business_type" not in cols:
                logger.info("approval_flows 缺少 business_type 列，开始补列 …")
                with real_engine.begin() as conn:
                    if real_engine.dialect.name == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE approval_flows ADD COLUMN IF NOT EXISTS "
                                "business_type VARCHAR(64) DEFAULT 'general'"
                            )
                        )
                        conn.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS ix_approval_flows_business_type "
                                "ON approval_flows (business_type)"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                "ALTER TABLE approval_flows ADD COLUMN business_type "
                                "VARCHAR(64) DEFAULT 'general'"
                            )
                        )
                logger.info("approval_flows.business_type 已补齐")
    except Exception as exc:
        logger.warning("approval_flows.business_type 兼容补列失败: %s", exc)


def ensure_product_query_indexes(engine: "Engine") -> None:
    """
    为 products 表补齐常用查询索引（按客户 unit、型号 model_number），
    便于列表筛选与 AI 工具链查库；对已存在库使用 IF NOT EXISTS 幂等。
    """
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        names = set(insp.get_table_names() or [])
    except Exception:
        names = set()

    if "products" not in names:
        return

    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_products_unit ON products (unit)",
        "CREATE INDEX IF NOT EXISTS ix_products_model_number ON products (model_number)",
    ]
    with engine.begin() as conn:
        for sql in stmts:
            try:
                conn.execute(text(sql))
            except Exception as e:
                logger.debug("创建 products 索引跳过: %s | %s", sql, e)

