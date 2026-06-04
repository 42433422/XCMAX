"""数据库初始化（lifespan 的子任务之一）。

从 ``app.fastapi_app.lifespan`` 抽出，便于：
- 单测单独覆盖 DDL/迁移逻辑；
- 复用（lifespan / 一次性 CLI / 测试 fixture 都能调）。

只暴露 ``initialize_databases_async`` 这一个对外入口；
``_run_ensure_ai_action_audit_table`` / ``_initialize_databases_sync`` 为内部协程。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from app.db import engine
from app.db.init_db import (
    ensure_product_query_indexes,
    ensure_sessions_account_meta_columns,
    ensure_sessions_enterprise_entitlement_columns,
    ensure_sessions_market_access_token_column,
    ensure_sessions_market_refresh_token_column,
    ensure_users_tenant_id_column,
    init_approval_tables,
    init_distillation_tables,
    init_extract_logs_tables,
    init_service_bridge_tables,
    init_template_tables,
    init_wechat_tasks_table,
    initialize_databases,
)

from .sqlite_paths import is_sqlite_url, resolve_effective_database_url, sqlite_db_file_from_url

logger = logging.getLogger(__name__)

_APP_ROOT = Path(__file__).resolve().parents[1]


async def initialize_databases_async(app: FastAPI) -> None:
    """异步初始化数据库（线程池执行同步初始化）。"""
    db_url = str(getattr(app.state.config, "DATABASE_URL", "") or "").strip()
    if db_url:
        try:
            safe = make_url(db_url).render_as_string(hide_password=True)
        except (ValueError, TypeError):
            safe = db_url
        logger.info("初始化数据库... (DATABASE_URL=%s)", safe)
    else:
        logger.info("初始化数据库... (DATABASE_URL 未设置，使用默认策略)")

    await asyncio.get_running_loop().run_in_executor(None, _initialize_databases_sync, app)

    try:
        from app.services.wechat_decrypt_autoconfig import (
            apply_runtime_env,
            ensure_pycryptodome,
            load_runtime_config,
        )

        apply_runtime_env(load_runtime_config())
        ok, detail = ensure_pycryptodome(auto_install=True)
        if ok:
            logger.debug("pycryptodome: %s", detail)
        else:
            logger.warning("pycryptodome 未就绪: %s", detail)
    except Exception as exc:
        logger.debug("wechat_decrypt runtime env apply skipped: %s", exc)


def _run_ensure_ai_action_audit_table() -> None:
    """加载审计 DDL 模块但不执行 app.services 包 __init__（避免牵连全量 application / 重型依赖）。"""
    path = _APP_ROOT / "services" / "ai_action_audit_service.py"
    spec = importlib.util.spec_from_file_location("_xcagi_ai_action_audit_service", str(path))
    mod = importlib.util.module_from_spec(spec)
    loader = spec.loader
    if loader is None:
        raise RuntimeError("无法加载 ai_action_audit_service")
    loader.exec_module(mod)
    mod.ensure_ai_action_audit_table()


def _initialize_databases_sync(app: FastAPI) -> None:
    """同步数据库初始化（在后台线程中执行）"""
    database_url = resolve_effective_database_url(getattr(app.state.config, "DATABASE_URL", None))
    try:
        if is_sqlite_url(database_url):
            initialize_databases()
            try:
                from app.db.init_db import sqlite_per_mod_copies_enabled
                from app.db.mod_dal import get_mod_dal
                from app.infrastructure.mods.mod_manager import get_mod_manager

                if sqlite_per_mod_copies_enabled():
                    mm = get_mod_manager()
                    ids = [m.id for m in (mm.list_loaded_mods() or []) if getattr(m, "id", None)]
                    if not ids:
                        ids = [m.id for m in mm.scan_mods() if getattr(m, "id", None)]
                    warm = get_mod_dal().ensure_mod_copies(ids)
                    logger.debug("Mod DAL warm copies: %s", warm)
                try:
                    from app.db.init_db import ensure_wechat_contact_tables_on_sqlite_mod_copies

                    ensure_wechat_contact_tables_on_sqlite_mod_copies(ids)
                except Exception as wechat_mod_tbl_exc:
                    logger.warning(
                        "SQLite Mod 副本 wechat_contacts 表补齐跳过: %s", wechat_mod_tbl_exc
                    )
            except Exception as mod_db_exc:
                logger.warning("SQLite 按 Mod 拆分母库副本时跳过: %s", mod_db_exc)
            sqlite_file = sqlite_db_file_from_url(database_url)
            if sqlite_file:
                init_wechat_tasks_table(sqlite_file)
                init_template_tables(sqlite_file)
            else:
                init_wechat_tasks_table()
                init_template_tables()
            try:
                from app.db.init_db import ensure_purchase_units_table, ensure_wechat_contact_tables

                ensure_wechat_contact_tables(engine, database_url=database_url)
                ensure_purchase_units_table(engine, database_url=database_url)
            except Exception as wechat_tbl_exc:
                logger.warning("ensure_wechat_contact_tables skipped: %s", wechat_tbl_exc)

        init_distillation_tables(engine)
        init_extract_logs_tables(engine)
        ensure_product_query_indexes(engine)
        cfg_db_url = database_url
        from app.db.init_db import ensure_runtime_auth_bootstrap

        ensure_runtime_auth_bootstrap(engine, database_url=cfg_db_url or None)
        ensure_users_tenant_id_column(engine, database_url=cfg_db_url or None)
        ensure_sessions_market_access_token_column(engine, database_url=cfg_db_url or None)
        ensure_sessions_market_refresh_token_column(engine, database_url=cfg_db_url or None)
        ensure_sessions_enterprise_entitlement_columns(engine, database_url=cfg_db_url or None)
        ensure_sessions_account_meta_columns(engine, database_url=cfg_db_url or None)
        try:
            init_approval_tables(engine)
        except Exception as approval_err:
            logger.warning("approval 表初始化失败（不影响主流程）: %s", approval_err)
        try:
            init_service_bridge_tables(engine)
        except Exception as bridge_err:
            logger.warning("service_bridge 表初始化失败（不影响主流程）: %s", bridge_err)

        if not is_sqlite_url(database_url):
            try:
                from app.db.bootstrap_mod import ensure_postgres_per_mod_databases
                from app.infrastructure.mods.mod_manager import get_mod_manager

                mm = get_mod_manager()
                mod_ids = [m.id for m in (mm.list_loaded_mods() or []) if getattr(m, "id", None)]
                if not mod_ids:
                    mod_ids = [m.id for m in mm.scan_mods() if getattr(m, "id", None)]
                created = ensure_postgres_per_mod_databases(mod_ids=mod_ids, migrate_new=True)
                if created:
                    logger.info("已自动创建并迁移 Mod 分库: %s", ", ".join(created))
            except Exception as mod_pg_exc:
                logger.warning("PostgreSQL Mod 分库自检跳过: %s", mod_pg_exc)

        try:
            _run_ensure_ai_action_audit_table()
        except Exception as audit_err:
            logger.warning("AI审计表初始化失败（不影响主流程）: %s", audit_err)
    except Exception as e:
        safe_url = str(database_url or "").strip()
        try:
            if safe_url:
                safe_url = make_url(safe_url).render_as_string(hide_password=True)
        except (ValueError, TypeError):
            pass
        logger.exception("数据库初始化失败 (DATABASE_URL=%s): %s", safe_url or "<default>", e)
        if is_sqlite_url(database_url):
            raise RuntimeError(
                "本地数据库初始化失败：请检查 userData/data/xcagi.db 权限或磁盘空间。"
            ) from e
        raise RuntimeError(
            "数据库初始化失败：请确认 PostgreSQL 已启动且 DATABASE_URL 可连通。"
        ) from e


__all__ = ["initialize_databases_async", "_initialize_databases_async", "_initialize_databases_sync", "_run_ensure_ai_action_audit_table"]


# 兼容旧路径：旧测试通过 ``app.fastapi_app.lifespan._initialize_databases_async`` patch 该符号。
_initialize_databases_async = initialize_databases_async
