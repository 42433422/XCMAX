"""FastAPI lifespan 延后加载：桌面冷启先监听 HTTP，重服务后台补齐。"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _desktop_fast_start_enabled() -> bool:
    raw = os.environ.get("XCAGI_DESKTOP_FAST_START", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _ensure_spa_fallback_after_deferred(app: FastAPI) -> None:
    """deferred / Mod 路由若追加在 SPA catch-all 之后，GET /api/* 会被吞成 404。"""
    try:
        from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

        ensure_spa_fallback_last(app)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("SPA fallback reorder after deferred routes skipped: %s", exc)


async def _deferred_route_registration(app: FastAPI) -> None:
    if not getattr(app.state, "deferred_routes_pending", False):
        return
    from app.fastapi_app.startup_timing import mark_startup
    from app.fastapi_routes import register_deferred_routes

    await asyncio.to_thread(register_deferred_routes, app)
    await asyncio.to_thread(_ensure_spa_fallback_after_deferred, app)
    app.state.deferred_routes_pending = False
    mark_startup("routes_ready")


async def _deferred_mod_bootstrap(app: FastAPI) -> None:
    if not getattr(app.state, "mods_deferred_bootstrap", False):
        return
    if getattr(app.state, "mods_routes_loaded", False):
        app.state.mods_deferred_bootstrap = False
        return
    from app.fastapi_app.mod_startup import bootstrap_mod_extensions_sync

    await asyncio.to_thread(bootstrap_mod_extensions_sync, app)
    app.state.mods_deferred_bootstrap = False


async def _deferred_heavy_startup(app: FastAPI) -> None:
    """Mod 分阶段挂载 + NeuroBus / 员工调度 / 云中继等，不阻塞 uvicorn 首包。"""
    from app.fastapi_app.startup_timing import mark_startup

    await asyncio.gather(
        _deferred_route_registration(app),
        _deferred_mod_bootstrap(app),
    )
    # Mod 后台挂载也可能再追加路由；再顶一次 SPA 到末尾。
    await asyncio.to_thread(_ensure_spa_fallback_after_deferred, app)
    try:
        from app.mod_sdk.desktop_deliverable import ensure_deliverable_runtime

        await ensure_deliverable_runtime(app)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Deliverable runtime setup skipped: %s", exc)

    try:
        from app.utils.performance.performance_initializer import init_performance_optimization

        init_performance_optimization(app)
        mark_startup("performance_optimizer_ready")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Performance optimizer init skipped: %s", exc)

    from app.fastapi_app.lifespan import (
        _init_employee_runtime_async,
        _init_mobile_relay_desktop_async,
        _init_neuro_ddd_async,
    )

    await _init_neuro_ddd_async(app)
    await _init_employee_runtime_async(app)
    await _init_mobile_relay_desktop_async(app)
    mark_startup("deferred_heavy_ready")

    from app.fastapi_app.node_role import passive_node_enabled

    if not passive_node_enabled():
        try:
            from app.desktop_runtime.backup_scheduler import start_backup_scheduler

            start_backup_scheduler()
        except RECOVERABLE_ERRORS as exc:
            logger.warning("⚠️ 桌面端定时备份调度器启动失败: %s", exc)


async def schedule_deferred_heavy_startup(app: FastAPI) -> None:
    if not _desktop_fast_start_enabled():
        return
    existing = getattr(app.state, "deferred_startup_task", None)
    if existing and not existing.done():
        return
    app.state.deferred_startup_task = asyncio.create_task(
        _deferred_heavy_startup(app),
        name="xcagi-deferred-heavy-startup",
    )


async def cancel_deferred_heavy_startup(app: FastAPI) -> None:
    task = getattr(app.state, "deferred_startup_task", None)
    if not task or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
