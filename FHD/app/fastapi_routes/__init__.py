"""
FastAPI 路由注册模块 — 编排各 mount 阶段与 RouteRegistry。
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from app.fastapi_routes.mounts import (
    register_business_routes,
    register_essential_compat_routes,
    register_health_routes,
    register_infrastructure_routes,
    register_lan_routes,
    register_legacy_compat_routes,
    register_neuro_migration_routes,
    register_neuro_routes,
)
from app.fastapi_routes.registry import RouteRegistry
from app.legacy.routes.legacy_gap import register_legacy_gap_routers
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

__all__ = [
    "register_all_routes",
    "register_bootstrap_routes",
    "register_deferred_routes",
    "register_legacy_gap_routers",
]


def _register_platform_shell_bootstrap(app: FastAPI) -> None:
    """验收 API 须在 deferred 路由前可用，避免 SPA fallback 对 /api/* 返回 404。"""
    try:
        from app.fastapi_routes.platform_shell_routes import router as platform_shell_router

        app.include_router(platform_shell_router)
        logger.info("Registered platform_shell bootstrap routes")
    except RECOVERABLE_ERRORS as exc:
        logger.warning("Platform shell bootstrap routes skipped: %s", exc)


def register_bootstrap_routes(app: FastAPI) -> None:
    """桌面 fast-start：health + infrastructure + platform-shell，尽快让验收 API 可响应。"""
    register_health_routes(app)
    register_infrastructure_routes(app)
    _register_platform_shell_bootstrap(app)


def register_deferred_routes(app: FastAPI) -> None:
    """业务/Neuro/LAN/legacy 路由；桌面 fast-start 下在 deferred 任务中注册。"""
    logger.info("Registering deferred FastAPI routes...")
    registry = RouteRegistry()

    register_business_routes(app, registry)
    registry.apply(app)

    conflicts = registry.detect_conflicts()
    for conflict in conflicts:
        logger.warning(
            "Route conflict: %s %s registered in %s",
            conflict.method,
            conflict.path,
            conflict.mounts,
        )

    register_neuro_routes(app)
    register_neuro_migration_routes(app)
    register_lan_routes(app)

    if os.environ.get("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        logger.info("Skipped legacy compat routes (XCAGI_SKIP_LEGACY_COMPAT_ROUTES)")
        register_essential_compat_routes(app)
    else:
        register_legacy_compat_routes(app)

    # Desktop fast-start registers the SPA catch-all before this deferred
    # phase.  Move it back to the end or every late /api route is present in
    # OpenAPI yet unreachable at runtime (the fallback returns a misleading
    # 404 first).
    from app.fastapi_routes.spa_fallback import ensure_spa_fallback_last

    ensure_spa_fallback_last(app)
    logger.info("Deferred FastAPI routes registered successfully")


def register_all_routes(app: FastAPI) -> None:
    """Register all FastAPI routes in deterministic phase order."""
    logger.info("Registering FastAPI routes...")
    register_bootstrap_routes(app)
    register_deferred_routes(app)
    logger.info("FastAPI routes registered successfully")
