"""Mod 分阶段启动：先挂载主客户 Mod，其余在后台 load，缩短 HTTP 可监听时间。"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_bg_lock = threading.Lock()
_bg_work_lock = threading.Lock()


def _load_bundled_host_mods(mm: Any) -> list[str]:
    """同步加载当前 SKU 宿主 bridge 包（数量少、侧栏依赖）。"""
    loaded: list[str] = []
    try:
        from app.mod_sdk.product_skus import bundled_mod_ids_for_sku, resolve_product_sku

        sku = resolve_product_sku()
        if not sku:
            return loaded
        for mid in bundled_mod_ids_for_sku(sku):
            mid = str(mid or "").strip()
            if not mid or mid in mm._loaded_mods:
                continue
            try:
                if mm.load_mod(mid):
                    loaded.append(mid)
            except RECOVERABLE_ERRORS:
                logger.debug("bundled mod load skipped: %s", mid, exc_info=True)
    except RECOVERABLE_ERRORS:
        logger.debug("bundled mod ids resolve skipped", exc_info=True)
    return loaded


def schedule_background_mod_load(app: Any) -> None:
    """在后台线程执行 load_all_mods + 补挂路由，避免阻塞 create_fastapi_app。"""
    with _bg_lock:
        existing = getattr(app.state, "mods_background_thread", None)
        if existing is not None and existing.is_alive():
            return
        if getattr(app.state, "mods_background_load_scheduled", False):
            return
        if getattr(app.state, "mods_full_load_done", False):
            return
        done = threading.Event()
        app.state.mods_background_load_done = done
        app.state.mods_background_load_error = None
        app.state.mods_background_load_scheduled = True

    def _work() -> None:
        try:
            # ModManager is process-global. Serializing workers prevents two app
            # factories from mutating its registry while routes are being built.
            with _bg_work_lock:
                from app.fastapi_app.startup_timing import mark_startup
                from app.infrastructure.mods.mod_manager import get_mod_manager, load_mod_routes

                mm = get_mod_manager()
                loaded = mm.load_all_mods()
                load_mod_routes(app, mm)
                app.state.mods_routes_loaded = True
                app.state.mods_full_load_done = True
                try:
                    from app.mod_sdk.employee_runtime import warm_employee_tool_registry

                    warm_employee_tool_registry()
                except RECOVERABLE_ERRORS:
                    logger.debug("employee tool warm scan skipped", exc_info=True)
                mark_startup("mod_background_done")
                logger.info(
                    "[mod_startup] background load_all_mods done (%s ids)",
                    len(loaded),
                )
        except BOUNDARY_ERRORS as exc:
            app.state.mods_background_load_error = repr(exc)
            logger.exception("[mod_startup] background load_all_mods failed")
        finally:
            app.state.mods_background_load_scheduled = False
            done.set()

    thread = threading.Thread(
        target=_work,
        name="xcagi-mod-background-load",
        daemon=True,
    )
    app.state.mods_background_thread = thread
    thread.start()


def wait_for_background_mod_load(app: Any, *, timeout: float = 30.0) -> bool:
    """Wait for this app's Mod worker so it cannot escape the app lifespan."""
    thread = getattr(app.state, "mods_background_thread", None)
    if thread is None:
        return True
    thread.join(timeout=max(0.0, timeout))
    if thread.is_alive():
        logger.warning("[mod_startup] background load still running at shutdown")
        return False
    return True


def bootstrap_mod_extensions_sync(app: Any, *, schedule_background: bool = True) -> None:
    """
    同步阶段：仅加载当前 SKU 宿主 bridge；客户定制 Mod 登录后按 entitlement 按需加载。
    """
    from app.infrastructure.mods.mod_manager import (
        get_mod_manager,
        is_mods_disabled,
        load_mod_routes,
        mount_on_disk_primary_client_mods,
    )

    app.state.mods_routes_loaded = False
    app.state.mods_full_load_done = False
    app.state.mods_background_load_scheduled = False

    if is_mods_disabled():
        app.state.mods_routes_loaded = True
        app.state.mods_full_load_done = True
        return

    mm = get_mod_manager()
    client_ids = mount_on_disk_primary_client_mods(mm)
    bundled = _load_bundled_host_mods(mm)
    load_mod_routes(app, mm)
    app.state.mods_routes_loaded = True
    try:
        from app.fastapi_app.startup_timing import mark_startup

        mark_startup("mod_staged")
    except RECOVERABLE_ERRORS:
        pass
    logger.info(
        "Mod extensions staged (client=%s, bundled=%s); %s",
        client_ids,
        len(bundled),
        "scheduling background load" if schedule_background else "background load deferred",
    )
    if schedule_background:
        schedule_background_mod_load(app)


__all__ = [
    "bootstrap_mod_extensions_sync",
    "schedule_background_mod_load",
    "wait_for_background_mod_load",
]
