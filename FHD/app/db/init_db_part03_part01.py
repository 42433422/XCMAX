# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


def ensure_sessions_market_refresh_token_column(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """补齐 ``sessions.market_refresh_token``（与 Alembic ``2026_05_22_sessions_market_refresh_token`` 一致）。"""
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "无法按 DATABASE_URL 创建引擎以补齐 sessions.market_refresh_token: %s", exc
            )
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("sessions")}
        if "market_refresh_token" in cols:
            return
        _facade().logger.info("sessions 缺少 market_refresh_token 列，正在补齐 …")
        with real_engine.begin() as conn:
            if real_engine.dialect.name == "postgresql":
                conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_refresh_token TEXT")
                )
            else:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN market_refresh_token TEXT"))
        _facade().logger.info("sessions.market_refresh_token 已补齐")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "sessions.market_refresh_token 兼容补列失败（可在仓库根执行 alembic upgrade head）：%s",
            exc,
        )


def ensure_sessions_enterprise_entitlement_columns(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """补齐 ``sessions.market_user_id`` / ``entitled_mod_ids_json``（企业版 Mod 隔离缓存）。"""
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "无法按 DATABASE_URL 创建引擎以补齐 sessions 企业权益列: %s", exc
            )
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
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
                _facade().logger.info("sessions 缺少 market_user_id 列，正在补齐 …")
                if dialect == "postgresql":
                    conn.execute(
                        text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_user_id INTEGER")
                    )
                else:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN market_user_id INTEGER"))
            if "entitled_mod_ids_json" not in cols:
                _facade().logger.info("sessions 缺少 entitled_mod_ids_json 列，正在补齐 …")
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS entitled_mod_ids_json TEXT"
                        )
                    )
                else:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN entitled_mod_ids_json TEXT"))
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "sessions 企业权益列兼容补列失败（可执行 alembic upgrade head）：%s", exc
        )


def ensure_sessions_account_meta_columns(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """补齐 sessions 账号类型 / 企业品牌 / 代管列。"""
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("无法创建引擎以补齐 sessions 账号元数据列: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
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
                _facade().logger.info("sessions 缺少 %s 列，正在补齐 …", name)
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
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("sessions 账号元数据列兼容补列失败: %s", exc)


def ensure_users_tenant_id_column(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """补齐 ``users.tenant_id``，避免旧桌面 SQLite 企业登录时查询 User 失败。"""
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("无法创建引擎以补齐 users.tenant_id: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("users")}
        if "tenant_id" in cols:
            return
        _facade().logger.info("users 缺少 tenant_id 列，正在补齐 …")
        with real_engine.begin() as conn:
            if real_engine.dialect.name == "postgresql":
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER"))
            else:
                conn.execute(text("ALTER TABLE users ADD COLUMN tenant_id INTEGER"))
        _facade().logger.info("users.tenant_id 已补齐")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("users.tenant_id 兼容补列失败: %s", exc)


def ensure_business_tenant_id_columns(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """为业务表补齐 ``tenant_id`` 列（多租户数据隔离作用域；nullable）。"""
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("无法创建引擎以补齐业务表 tenant_id: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
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
        "templates",
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
                _facade().logger.info("%s 缺少 tenant_id 列，正在补齐 …", table)
                if dialect == "postgresql":
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
                    )
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER"))
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("业务表 tenant_id 兼容补列失败: %s", exc)


def ensure_user_profile_columns(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """补齐 ``users.tier`` / ``users.industry_id``，管理端用户等级与行业编辑依赖。"""
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("无法创建引擎以补齐 users.tier/industry_id: %s", exc)
    if real_engine is None and engine is not None:
        real_engine = engine
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables:
            return
        cols = {c["name"] for c in insp.get_columns("users")}
        dialect = real_engine.dialect.name
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
                _facade().logger.info("users 缺少 %s 列，正在补齐 …", name)
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
        _facade().logger.info("users 账号/行业列已补齐")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("users 账号/行业列兼容补列失败: %s", exc)
