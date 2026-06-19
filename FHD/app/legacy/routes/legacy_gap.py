"""Legacy gap routers (opt-in only)."""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_LEGACY_GAP_DOMAIN_MODULES: tuple[str, ...] = (
    "app.fastapi_routes.domains.conversation.routes",
    "app.fastapi_routes.domains.excel.routes",
    "app.fastapi_routes.domains.product.routes",
    "app.fastapi_routes.domains.static.routes",
    "app.fastapi_routes.domains.system.routes",
    "app.fastapi_routes.domains.wechat.routes",
    "app.fastapi_routes.domains.shipment.routes",
)


def register_legacy_gap_routers(app: FastAPI) -> None:
    for mod_path in _LEGACY_GAP_DOMAIN_MODULES:
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
