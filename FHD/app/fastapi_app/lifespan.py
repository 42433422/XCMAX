"""FastAPI lifespan：数据库、Mod、NeuroBus 启动与关闭。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import make_url

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .sqlite_paths import is_sqlite_url, resolve_effective_database_url

logger = logging.getLogger(__name__)


def _desktop_fast_start_enabled() -> bool:
    import os

    raw = os.environ.get("XCAGI_DESKTOP_FAST_START", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用生命周期管理"""
    logger.info("🚀 FastAPI 应用启动中...")

    from app.fastapi_app.startup_timing import mark_startup

    mark_startup("lifespan_begin")

    from app.neuro_async_bridge import set_neuro_main_loop

    set_neuro_main_loop(asyncio.get_running_loop())

    # Schema verification must finish before any Mod/runtime initialization can
    # touch the database. This makes a stale revision a real startup barrier.
    await _initialize_databases_async(app)
    await _init_mods_async(app)

    mark_startup("lifespan_db_done")

    try:
        from app.application.desktop_admin_gate import purge_admin_sessions_on_desktop

        purged = await asyncio.to_thread(purge_admin_sessions_on_desktop)
        if purged:
            logger.info("desktop admin gate: startup purged %s admin session(s)", purged)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("desktop admin session purge skipped: %s", exc)

    fast_start = _desktop_fast_start_enabled()

    if fast_start:
        from app.fastapi_app.deferred_startup import schedule_deferred_heavy_startup

        await schedule_deferred_heavy_startup(app)
    else:
        try:
            from app.mod_sdk.desktop_deliverable import ensure_deliverable_runtime

            await ensure_deliverable_runtime(app)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("Deliverable runtime setup skipped: %s", exc)

        try:
            from app.utils.performance_initializer import init_performance_optimization

            init_performance_optimization(app)
            mark_startup("performance_optimizer_ready")
        except RECOVERABLE_ERRORS as exc:
            logger.warning("Performance optimizer init skipped: %s", exc)

        await _init_neuro_ddd_async(app)
        await _init_employee_runtime_async(app)
        await _init_mobile_relay_desktop_async(app)

        try:
            from app.desktop_runtime.backup_scheduler import start_backup_scheduler

            start_backup_scheduler()
        except RECOVERABLE_ERRORS as exc:
            logger.warning("⚠️ 桌面端定时备份调度器启动失败: %s", exc)

    mark_startup("lifespan_ready")
    logger.info("✅ FastAPI 应用启动完成%s", "（重服务后台加载）" if fast_start else "")

    yield

    logger.info("🛑 FastAPI 应用关闭中...")
    if fast_start:
        from app.fastapi_app.deferred_startup import cancel_deferred_heavy_startup

        await cancel_deferred_heavy_startup(app)
    try:
        from app.desktop_runtime.backup_scheduler import stop_backup_scheduler

        stop_backup_scheduler()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("⚠️ 桌面端定时备份调度器关闭失败: %s", exc)
    try:
        from app.application.employee_runtime.scheduler import stop_employee_scheduler

        stop_employee_scheduler()
        logger.info("✅ 员工本地调度器已关闭")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ 员工本地调度器关闭失败: %s", e)
    try:
        from app.services.mobile_relay_desktop_client import stop_desktop_relay_poller

        stop_desktop_relay_poller()
        logger.info("✅ 移动端云中继轮询已关闭")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ 移动端云中继轮询关闭失败: %s", e)
    try:
        from app.neuro_bus.bus_setup import teardown_neuro_bus

        await teardown_neuro_bus()
        logger.info("✅ 神经总线已关闭")
        try:
            from app.neuro_bus.health_monitor import get_health_monitor

            get_health_monitor().stop_monitoring()
            task = getattr(app.state, "neuro_health_monitor_task", None)
            if task and not task.done():
                task.cancel()
            logger.info("✅ HealthMonitor 监控循环已停止")
        except RECOVERABLE_ERRORS as hm_err:
            logger.warning("⚠️ HealthMonitor 关闭失败: %s", hm_err)
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ 神经总线关闭失败: %s", e)


async def _initialize_databases_async(app: FastAPI):
    """异步初始化数据库"""
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


def _initialize_databases_sync(app: FastAPI):
    """Verify the migration-owned schema and provision migration-owned Mod DBs."""
    database_url = resolve_effective_database_url(getattr(app.state.config, "DATABASE_URL", None))
    # Narrow test fixtures construct their own in-memory tables and do not own a
    # persistent Alembic revision.
    if bool(getattr(app.state.config, "TESTING", False)):
        return

    # Production is migrated by the container entrypoint; desktop is migrated by
    # Electron before the backend starts.  Missing/stale revisions therefore stop
    # startup instead of being silently repaired by create_all/ensure_*.
    from app.db import _create_engine_for_url
    from app.db.schema_contract import assert_database_schema_at_head

    schema_engine = _create_engine_for_url(database_url)
    try:
        assert_database_schema_at_head(schema_engine)
    finally:
        schema_engine.dispose()

    from app.infrastructure.mods.mod_manager import get_mod_manager

    mm = get_mod_manager()
    mod_ids = [m.id for m in (mm.list_loaded_mods() or []) if getattr(m, "id", None)]
    if not mod_ids:
        mod_ids = [m.id for m in mm.scan_mods() if getattr(m, "id", None)]

    if is_sqlite_url(database_url):
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        ensure_sqlite_per_mod_database_copies(mod_ids)
    else:
        from app.db.ensure_mod_postgres import ensure_postgres_per_mod_databases

        created = ensure_postgres_per_mod_databases(mod_ids=mod_ids, migrate_new=True)
        if created:
            logger.info("已自动创建并迁移 Mod 分库: %s", ", ".join(created))

    # From this point onward application-created engines reject DDL. Alembic
    # runs in its own process/engine before startup and remains the only writer.
    from app.db import _get_engine_for_url
    from app.db.schema_contract import activate_runtime_ddl_guard, install_runtime_ddl_guard

    activate_runtime_ddl_guard()
    install_runtime_ddl_guard(_get_engine_for_url(database_url))


async def _init_neuro_ddd_async(app: FastAPI):
    """异步初始化 NeuroBus，并注册默认意图域（与对话意图桥接共用）。"""
    import os

    raw = os.environ.get("XCAGI_NEURO_INTENT", "1").strip().lower()
    if raw in {"0", "false", "off", "no"}:
        logger.info(
            "神经总线未启用（XCAGI_NEURO_INTENT=%s）", os.environ.get("XCAGI_NEURO_INTENT", "")
        )
        return
    try:
        from app.neuro_bus.bus_setup import get_neuro_bus_manager
        from app.neuro_bus.register_runtime import register_neuro_runtime

        bus = await register_neuro_runtime()
        app.state.neuro_bus = bus
        app.state.neuro_bus_manager = get_neuro_bus_manager()
        logger.info("✅ 神经总线已启动，域: %s", bus.registered_domains)
        try:
            from app.neuro_bus.health_monitor import get_health_monitor

            monitor = get_health_monitor()
            app.state.neuro_health_monitor_task = asyncio.create_task(monitor.start_monitoring())
            logger.info("✅ HealthMonitor 监控循环已启动")
        except RECOVERABLE_ERRORS as hm_err:
            logger.warning("⚠️ HealthMonitor 启动失败: %s", hm_err)

        # 注册认知层 / 潜意识层 / 进化层 handler（Phase 2-4 接线）
        try:
            from app.domain.neuro.register_cognition_handlers import register_cognition_handlers

            cognition_result = register_cognition_handlers()
            app.state.neuro_cognition = cognition_result
            if cognition_result.get("enabled"):
                logger.info(
                    "✅ 认知层 handler 已注册（%d 个）",
                    cognition_result.get("handler_count", 0),
                )
        except RECOVERABLE_ERRORS as cog_err:
            logger.warning("⚠️ 认知层 handler 注册失败: %s", cog_err)
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ 神经总线初始化失败: %s", e)


async def _init_employee_runtime_async(app: FastAPI):
    """Initialize local AI employee triggers and cron scheduler."""
    try:
        from app.application.employee_runtime.scheduler import start_employee_scheduler
        from app.application.employee_runtime.triggers import refresh_employee_triggers

        trigger_status = await asyncio.to_thread(refresh_employee_triggers)
        scheduler_status = await asyncio.to_thread(start_employee_scheduler)
        app.state.employee_triggers = trigger_status
        app.state.employee_scheduler = scheduler_status
        logger.info(
            "✅ 员工运行时已启动 triggers=%d scheduler_running=%s",
            len(trigger_status.get("registered") or []),
            scheduler_status.get("running"),
        )
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ 员工运行时初始化失败: %s", e)


async def _init_mobile_relay_desktop_async(app: FastAPI):
    """Resume desktop relay polling when this runtime has a saved cloud binding."""
    try:
        from app.services.mobile_relay_desktop_client import (
            _migrate_legacy_config_once,
            start_desktop_relay_poller,
        )

        # 源码升级后，旧的仓库根回落配置一次性迁移到稳定路径，保住既有配对，
        # 再恢复轮询（否则桌面会以与手机已配对 relay 不同的身份去 poll，任务卡在「排队中」）。
        await asyncio.to_thread(_migrate_legacy_config_once)
        running = await asyncio.to_thread(start_desktop_relay_poller)
        app.state.mobile_relay_desktop_running = running
        if running:
            logger.info("✅ 移动端云中继轮询已启动")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ 移动端云中继轮询启动失败: %s", e)


async def _init_mods_async(app: FastAPI):
    """初始化 Mod 扩展（create_fastapi_app 已分阶段挂载；此处仅补偿失败重试）。"""
    if getattr(app.state, "mods_deferred_bootstrap", False):
        logger.info("Mod bootstrap deferred; skipping lifespan mod init")
        return
    if getattr(app.state, "mods_full_load_done", False):
        logger.info("Mod extensions fully loaded; skipping lifespan mod init")
        return
    if getattr(app.state, "mods_background_load_scheduled", False):
        logger.info("Mod background load in progress; skipping lifespan duplicate load")
        return
    if getattr(app.state, "mods_routes_loaded", False):
        logger.info("Mod routes staged; skipping lifespan full sync load")
        return
    try:
        from app.fastapi_app.mod_startup import bootstrap_mod_extensions_sync

        await asyncio.to_thread(bootstrap_mod_extensions_sync, app)
        logger.info("✅ Mod 扩展分阶段加载已启动（lifespan 补偿路径）")
    except RECOVERABLE_ERRORS as e:
        logger.warning("⚠️ Mod 扩展初始化失败: %s", e)
