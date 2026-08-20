# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


def ensure_mobile_push_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """Idempotently create device-token and notification-outbox tables.

    Conversation completion can enqueue a mobile notification before any
    mobile API route has been visited.  These tables therefore belong to the
    desktop runtime bootstrap instead of route-local lazy initialization.
    """
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.models.mobile_notification import MobileNotificationOutbox

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        tables = set(inspect(real_engine).get_table_names() or [])
        model_tables = [
            _facade()._orm_table(MobileDeviceToken),
            _facade()._orm_table(MobileNotificationOutbox),
        ]
        missing = [table for table in model_tables if table.name not in tables]
        if missing:
            _facade().logger.info(
                "缺少移动推送表 %s，正在通过 ORM 创建 …", [t.name for t in missing]
            )
            Base.metadata.create_all(real_engine, tables=missing, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning("ensure_mobile_push_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_runtime_auth_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = False,
) -> None:
    """按运行时 DATABASE_URL 幂等补齐 users/sessions/RBAC/库存表（SQLite 或 PostgreSQL）。"""
    from app.fastapi_app.sqlite_paths import is_sqlite_url, resolve_effective_database_url

    url = (database_url or resolve_effective_database_url() or "").strip()
    if not url:
        return
    if is_sqlite_url(url):
        _facade().ensure_sqlite_auth_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_sqlite_rbac_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_sqlite_inventory_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_sqlite_enterprise_business_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_user_preferences_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_neuro_event_log_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_sqlite_im_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_employee_run_log_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_ai_conversation_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_mobile_push_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_sqlite_etl_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_erp_bootstrap(engine, database_url=url, swallow_errors=swallow_errors)
    else:
        _facade().ensure_postgresql_auth_bootstrap(engine, database_url=url)
        _facade().ensure_user_preferences_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_neuro_event_log_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_sqlite_im_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_employee_run_log_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_ai_conversation_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_mobile_push_bootstrap(
            engine, database_url=url, swallow_errors=swallow_errors
        )
        _facade().ensure_erp_bootstrap(engine, database_url=url, swallow_errors=swallow_errors)


def ensure_erp_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """Idempotently create ERP tables absorbed from Odoo 18 (sales + double-entry accounting).

    ``SalesOrder``/``SalesOrderItem`` back the sales-to-payment closed loop;
    ``ChartOfAccount``/``JournalEntry``/``JournalEntryLine`` back double-entry
    bookkeeping.  These models are autoloaded by the app but have no dedicated
    ``ensure_*_bootstrap``, so PostgreSQL/SQLite would otherwise fail on query.
    """
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.accounting import ChartOfAccount, JournalEntry, JournalEntryLine
    from app.db.models.crm import CustomerAddress
    from app.db.models.mrp import Bom, BomLine, ManufacturingOrder, ManufacturingOrderLine
    from app.db.models.product import UomCategory, UomUnit
    from app.db.models.receivable_allocation import ReceivableAllocation
    from app.db.models.sales import SalesOrder, SalesOrderItem

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        tables = set(inspect(real_engine).get_table_names() or [])
        model_tables = [
            _facade()._orm_table(SalesOrder),
            _facade()._orm_table(SalesOrderItem),
            _facade()._orm_table(ChartOfAccount),
            _facade()._orm_table(JournalEntry),
            _facade()._orm_table(JournalEntryLine),
            _facade()._orm_table(ReceivableAllocation),
            _facade()._orm_table(Bom),
            _facade()._orm_table(BomLine),
            _facade()._orm_table(ManufacturingOrder),
            _facade()._orm_table(ManufacturingOrderLine),
            _facade()._orm_table(CustomerAddress),
            _facade()._orm_table(UomCategory),
            _facade()._orm_table(UomUnit),
        ]
        missing = [table for table in model_tables if table.name not in tables]
        if missing:
            _facade().logger.info("缺少 ERP 表 %s，正在通过 ORM 创建 …", [t.name for t in missing])
            Base.metadata.create_all(real_engine, tables=missing, checkfirst=True)
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning("ensure_erp_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_postgresql_auth_bootstrap(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """空 PostgreSQL 库在未跑 Alembic 时缺少 users/sessions，登录会抛出异常并带上 error_id。

    幂等创建最小表结构；仅在 ``users`` 表无任何行时写入管理员（优先 ``ADMIN_*`` 环境变量，
    否则 ``admin`` / ``admin123``，与 ``d8f5e2a1c9b3_add_rbac_tables`` 种子行为一致。
    业务表仍应通过 ``alembic upgrade head`` 补齐。
    """
    from sqlalchemy import inspect, text

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "postgresql":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables:
            _facade().logger.info("PostgreSQL 缺少 users 表，正在创建（空库登录引导）…")
            with real_engine.begin() as conn:
                conn.execute(
                    text(
                        "\n                        CREATE TABLE users (\n                            id BIGSERIAL PRIMARY KEY,\n                            username VARCHAR NOT NULL UNIQUE,\n                            password VARCHAR NOT NULL,\n                            display_name VARCHAR DEFAULT '',\n                            email VARCHAR DEFAULT '',\n                            role VARCHAR DEFAULT 'user',\n                            is_active BOOLEAN DEFAULT TRUE,\n                            mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,\n                            tier VARCHAR(32) NOT NULL DEFAULT 'personal',\n                            industry_id VARCHAR(32) NOT NULL DEFAULT '通用',\n                            created_by BIGINT REFERENCES users(id),\n                            created_at TIMESTAMP,\n                            last_login TIMESTAMP,\n                            wx_openid VARCHAR(64),\n                            wx_unionid VARCHAR(64),\n                            wx_avatar_url TEXT\n                        )\n                        "
                    )
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_users_wx_unionid ON users (wx_unionid)")
                )
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "sessions" not in tables:
            if "users" not in tables:
                _facade().logger.warning(
                    "ensure_postgresql_auth_bootstrap: users 仍不存在，跳过 sessions 创建"
                )
                return
            _facade().logger.info("PostgreSQL 缺少 sessions 表，正在创建 …")
            with real_engine.begin() as conn:
                conn.execute(
                    text(
                        "\n                        CREATE TABLE sessions (\n                            id BIGSERIAL PRIMARY KEY,\n                            session_id VARCHAR NOT NULL UNIQUE,\n                            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n                            created_at TIMESTAMP,\n                            expires_at TIMESTAMP NOT NULL,\n                            market_access_token TEXT,\n                            market_refresh_token TEXT\n                        )\n                        "
                    )
                )
        _facade()._seed_default_admin_user(real_engine)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "ensure_postgresql_auth_bootstrap 失败（可改用手工 alembic）：%s", exc, exc_info=True
        )


def ensure_sessions_market_access_token_column(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> None:
    """补齐 ``sessions.market_access_token``（与 Alembic ``2026_05_10_sessions_market_access_token`` 一致）。

    旧库若未跑迁移，ORM 写入会话行时会触发 ``OperationalError``，登录在密码校验通过后仍失败，
    界面仅显示「登录失败，请稍后重试」与 ``error_id``。

    传入 ``database_url`` 时用其与 ``Config.DATABASE_URL`` 对齐的连接执行 DDL，避免仅依赖
    请求上下文的 Mod 选库与 ``_get_engine()`` 不一致导致补列落在错误的文件/库上。
    """
    from sqlalchemy import inspect, text

    real_engine: _facade().Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "无法按 DATABASE_URL 创建引擎以补齐 sessions.market_access_token: %s", exc
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
        if "market_access_token" in cols:
            return
        _facade().logger.info("sessions 缺少 market_access_token 列，正在补齐 …")
        with real_engine.begin() as conn:
            if real_engine.dialect.name == "postgresql":
                conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_access_token TEXT")
                )
            else:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN market_access_token TEXT"))
        _facade().logger.info("sessions.market_access_token 已补齐")
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
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
                "数据库表 sessions 缺少 market_access_token 列且自动补齐失败。请在 FHD 仓库根执行: alembic upgrade head"
            )
    except RuntimeError:
        raise
    except _facade().RECOVERABLE_ERRORS as verify_exc:
        _facade().logger.warning("sessions.market_access_token 列校验跳过: %s", verify_exc)
