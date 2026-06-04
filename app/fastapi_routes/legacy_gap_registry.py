"""Legacy gap domain routers registration (replaces legacy_host_routers.py)."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

LEGACY_GAP_DOMAIN_MODULES: tuple[str, ...] = (
    "app.fastapi_routes.domains.conversation.routes",
    "app.fastapi_routes.domains.excel.routes",
    "app.fastapi_routes.domains.product.routes",
    "app.fastapi_routes.domains.static.routes",
    "app.fastapi_routes.domains.system.routes",
    "app.fastapi_routes.domains.wechat.routes",
    "app.fastapi_routes.domains.shipment.routes",
)

LEGACY_GAP_MODULE_NAMES: tuple[str, ...] = (
    "legacy_conversation",
    "legacy_excel",
    "legacy_products",
    "legacy_static",
    "legacy_system",
    "legacy_wechat",
    "legacy_workflow",
)


def register_legacy_gap_routers(app: FastAPI) -> None:
    """Include legacy gap routers on the FastAPI app."""
    for mod_path in LEGACY_GAP_DOMAIN_MODULES:
        mod = importlib.import_module(mod_path)
        router = mod.router
        if not router.routes:
            logger.debug("Skipped empty legacy gap router: %s", mod_path)
            continue
        app.include_router(router)
        logger.info(
            "Registered %s (%d routes, deprecated=%s)",
            mod_path,
            len(router.routes),
            getattr(router, "deprecated", False),
        )
