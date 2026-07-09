"""
Domain-specific table initialization and column migration helpers.

Split from ``init_db.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.db._init_db_facade import module as _init_db_facade
from app.utils.external_sqlite import sqlite_conn
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

def init_wechat_tasks_table(db_path: str | None = None) -> None:
    """初始化 wechat_tasks 表（存放从微信解析出来的任务）"""
    db_path = db_path or _init_db_facade().get_db_path("products.db")
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


def init_distillation_tables(engine: Engine) -> None:
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
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_used ON distillation_log(used_for_training)")
        )


def init_extract_logs_tables(engine: Engine) -> None:
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
    db_path = db_path or _init_db_facade().get_db_path("products.db")
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


def init_template_tables_for_engine(engine: Engine) -> None:
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

def ensure_sessions_market_access_token_column(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """补齐 ``sessions.market_access_token``（与 Alembic ``2026_05_10_sessions_market_access_token`` 一致）。

    旧库若未跑迁移，ORM 写入会话行时会触发 ``OperationalError``，登录在密码校验通过后仍失败，
    界面仅显示「登录失败，请稍后重试」与 ``error_id``。

    传入 ``database_url`` 时用其与 ``Config.DATABASE_URL`` 对齐的连接执行 DDL，避免仅依赖
    请求上下文的 Mod 选库与 ``_get_engine()`` 不一致导致补列落在错误的文件/库上。
    """
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning(
                "无法按 DATABASE_URL 创建引擎以补齐 sessions.market_access_token: %s", exc
            )
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("sessions")}
        if "market_access_token" in cols:
            return
        logger.info("sessions 缺少 market_access_token 列，正在补齐 …")
        with real_engine.begin() as conn:
            if real_engine.dialect.name == "postgresql":
                conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_access_token TEXT")
                )
            else:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN market_access_token TEXT"))
        logger.info("sessions.market_access_token 已补齐")
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "sessions.market_access_token 兼容补列失败（可在仓库根执行 alembic upgrade head）：%s",
            exc,
        )

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("sessions")}
        if "market_access_token" not in cols:
            raise RuntimeError(
                "数据库表 sessions 缺少 market_access_token 列且自动补齐失败。"
                "请在 FHD 仓库根执行: alembic upgrade head"
            )
    except RuntimeError:
        raise
    except RECOVERABLE_ERRORS as verify_exc:
        logger.warning("sessions.market_access_token 列校验跳过: %s", verify_exc)


def ensure_sessions_market_refresh_token_column(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """补齐 ``sessions.market_refresh_token``（与 Alembic ``2026_05_22_sessions_market_refresh_token`` 一致）。"""
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning(
                "无法按 DATABASE_URL 创建引擎以补齐 sessions.market_refresh_token: %s", exc
            )
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("sessions")}
        if "market_refresh_token" in cols:
            return
        logger.info("sessions 缺少 market_refresh_token 列，正在补齐 …")
        with real_engine.begin() as conn:
            if real_engine.dialect.name == "postgresql":
                conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_refresh_token TEXT")
                )
            else:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN market_refresh_token TEXT"))
        logger.info("sessions.market_refresh_token 已补齐")
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "sessions.market_refresh_token 兼容补列失败（可在仓库根执行 alembic upgrade head）：%s",
            exc,
        )


def ensure_sessions_enterprise_entitlement_columns(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """补齐 ``sessions.market_user_id`` / ``entitled_mod_ids_json``（企业版 Mod 隔离缓存）。"""
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("无法按 DATABASE_URL 创建引擎以补齐 sessions 企业权益列: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("sessions")}
        dialect = real_engine.dialect.name
        with real_engine.begin() as conn:
            if "market_user_id" not in cols:
                logger.info("sessions 缺少 market_user_id 列，正在补齐 …")
                if dialect == "postgresql":
                    conn.execute(
                        text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_user_id INTEGER")
                    )
                else:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN market_user_id INTEGER"))
            if "entitled_mod_ids_json" not in cols:
                logger.info("sessions 缺少 entitled_mod_ids_json 列，正在补齐 …")
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS entitled_mod_ids_json TEXT"
                        )
                    )
                else:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN entitled_mod_ids_json TEXT"))
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "sessions 企业权益列兼容补列失败（可执行 alembic upgrade head）：%s",
            exc,
        )


def ensure_sessions_account_meta_columns(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """补齐 sessions 账号类型 / 企业品牌 / 代管列。"""
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("无法创建引擎以补齐 sessions 账号元数据列: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    additions = [
        ("account_kind", "VARCHAR(32)", "'enterprise'"),
        ("company_brand", "VARCHAR(256)", "''"),
        ("market_is_admin", "BOOLEAN", "FALSE"),
        ("market_is_enterprise", "BOOLEAN", "FALSE"),
        ("impersonating_market_user_id", "INTEGER", None),
        ("impersonating_username", "VARCHAR(128)", "''"),
        ("tenant_id", "INTEGER", None),
        ("market_membership_tier", "VARCHAR(32)", None),
    ]
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("sessions")}
        dialect = real_engine.dialect.name
        with real_engine.begin() as conn:
            for name, col_type, default_sql in additions:
                if name in cols:
                    continue
                logger.info("sessions 缺少 %s 列，正在补齐 …", name)
                if dialect == "postgresql":
                    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
                    conn.execute(
                        text(
                            f"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {name} {col_type}{default_clause}"
                        )
                    )
                else:
                    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
                    conn.execute(
                        text(f"ALTER TABLE sessions ADD COLUMN {name} {col_type}{default_clause}")
                    )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("sessions 账号元数据列兼容补列失败: %s", exc)


def ensure_users_tenant_id_column(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """补齐 ``users.tenant_id``，避免旧桌面 SQLite 企业登录时查询 User 失败。"""
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("无法创建引擎以补齐 users.tenant_id: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("users")}
        if "tenant_id" in cols:
            return
        logger.info("users 缺少 tenant_id 列，正在补齐 …")
        with real_engine.begin() as conn:
            if real_engine.dialect.name == "postgresql":
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER"))
            else:
                conn.execute(text("ALTER TABLE users ADD COLUMN tenant_id INTEGER"))
        logger.info("users.tenant_id 已补齐")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("users.tenant_id 兼容补列失败: %s", exc)


def ensure_business_tenant_id_columns(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """为业务表补齐 ``tenant_id`` 列（多租户数据隔离作用域；nullable）。"""
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("无法创建引擎以补齐业务表 tenant_id: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    business_tables = (
        "products",
        "customers",
        "purchase_units",
        "materials",
        "shipment_records",
        "financial_transactions",
        "suppliers",
        "purchase_orders",
        "purchase_order_items",
        "purchase_inbounds",
        "purchase_inbound_items",
        "warehouses",
        "storage_locations",
        "inventory_ledger",
        "inventory_transactions",
    )
    try:
        insp = inspect(real_engine)
        existing = set(insp.get_table_names() or [])
        dialect = real_engine.dialect.name
        with real_engine.begin() as conn:
            for table in business_tables:
                if table not in existing:
                    continue
                cols = {c["name"] for c in insp.get_columns(table)}
                if "tenant_id" in cols:
                    continue
                logger.info("%s 缺少 tenant_id 列，正在补齐 …", table)
                if dialect == "postgresql":
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
                    )
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER"))
    except RECOVERABLE_ERRORS as exc:
        logger.warning("业务表 tenant_id 兼容补列失败: %s", exc)


def ensure_user_profile_columns(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """补齐 ``users.tier`` / ``users.industry_id``，管理端用户等级与行业编辑依赖。"""
    from sqlalchemy import inspect, text

    real_engine: Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("无法创建引擎以补齐 users.tier/industry_id: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("users")}
        dialect = real_engine.dialect.name
        # entitled_industries 为 JSON 列：postgresql 用 JSONB，其他方言用 TEXT
        json_type = "JSONB" if dialect == "postgresql" else "TEXT"
        additions = [
            ("tier", "VARCHAR(32)", "'personal'"),
            ("industry_id", "VARCHAR(32)", "'通用'"),
            ("account_tier", "VARCHAR(32)", None),
            ("budget_range", "VARCHAR(32)", None),
            ("entitled_industries", json_type, None),
            ("failed_login_attempts", "INTEGER", "0"),
            ("locked_until", "TIMESTAMP", None),
            ("email_verified", "BOOLEAN", "FALSE"),
        ]
        with real_engine.begin() as conn:
            for name, col_type, default_sql in additions:
                if name in cols:
                    continue
                logger.info("users 缺少 %s 列，正在补齐 …", name)
                default_clause = f" DEFAULT {default_sql}" if default_sql else ""
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {col_type}{default_clause}"
                        )
                    )
                else:
                    conn.execute(
                        text(f"ALTER TABLE users ADD COLUMN {name} {col_type}{default_clause}")
                    )
        logger.info("users 账号/行业列已补齐")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("users 账号/行业列兼容补列失败: %s", exc)


def init_im_tables(engine: Engine | None = None, *, database_url: str | None = None) -> None:
    """在主库上创建企业内部 IM V0 表（im_conversations / members / messages）。"""
    if engine is None:
        if database_url:
            from app.db import _create_engine_for_url

            engine = _create_engine_for_url(database_url)
        else:
            from app.db import _get_engine

            engine = _get_engine()

    from app.db.base import Base
    from app.db.models.im import (  # noqa: F401
        ImConversation,
        ImConversationMember,
        ImMessage,
    )

    target_tables = [
        ImConversation.__table__,
        ImConversationMember.__table__,
        ImMessage.__table__,
    ]
    Base.metadata.create_all(engine, tables=target_tables, checkfirst=True)


def init_approval_tables(engine: Engine) -> None:
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
    except RECOVERABLE_ERRORS:
        pass

    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
    except RECOVERABLE_ERRORS as exc:
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
    except RECOVERABLE_ERRORS as exc:
        logger.warning("approval_flows.business_type 兼容补列失败: %s", exc)


def ensure_product_query_indexes(engine: Engine) -> None:
    """
    为 products 表补齐常用查询索引（按客户 unit、型号 model_number），
    便于列表筛选与 AI 工具链查库；对已存在库使用 IF NOT EXISTS 幂等。
    """
    from sqlalchemy import inspect, text

    try:
        insp = inspect(engine)
        names = set(insp.get_table_names() or [])
    except RECOVERABLE_ERRORS:
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
            except RECOVERABLE_ERRORS as e:
                logger.debug("创建 products 索引跳过: %s | %s", sql, e)


def init_service_bridge_tables(engine: Engine) -> None:
    """在主库创建客服桥接表（service_requests / service_bridge_config）。"""
    from app.db.base import Base
    from app.db.models.service_request import (  # noqa: F401
        ServiceBridgeConfig,
        ServiceRequest,
    )

    target_tables = [
        ServiceRequest.__table__,
        ServiceBridgeConfig.__table__,
    ]

    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine

        real_engine = _get_real_engine()
    except RECOVERABLE_ERRORS:
        pass

    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
        logger.info("service_bridge 表已就绪")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("service_bridge 表 create_all 失败: %s", exc)


def init_persona_tables(engine: Engine) -> None:
    """在主库创建 persona 画像表（persona_profile / persona_event_log）。

    注：本仓库 alembic 链在普通启动时不触发（建表统一走 init_db + lifespan），
    故 persona 两张表必须在此显式 create_all，否则 PersonaRepositoryImpl 落盘会失败。
    """
    from app.db.base import Base
    from app.infrastructure.persona.models import (  # noqa: F401
        PersonaEventLogModel,
        PersonaProfileModel,
    )

    target_tables = [
        PersonaProfileModel.__table__,
        PersonaEventLogModel.__table__,
    ]

    real_engine = engine
    try:
        from app.db import _get_engine as _get_real_engine

        real_engine = _get_real_engine()
    except RECOVERABLE_ERRORS:
        pass

    try:
        Base.metadata.create_all(real_engine, tables=target_tables, checkfirst=True)
        logger.info("persona 表已就绪")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("persona 表 create_all 失败: %s", exc)
