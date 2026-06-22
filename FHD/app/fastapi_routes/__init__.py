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

logger = logging.getLogger(__name__)

__all__ = ["register_all_routes", "register_legacy_gap_routers"]


def register_all_routes(app: FastAPI) -> None:
    """Register all FastAPI routes in deterministic phase order."""
    logger.info("Registering FastAPI routes...")
    registry = RouteRegistry()

    register_infrastructure_routes(app)
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

    register_health_routes(app)
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

    logger.info("FastAPI routes registered successfully")
