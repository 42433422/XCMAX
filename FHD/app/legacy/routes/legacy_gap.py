"""Legacy gap routers (opt-in only)."""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_LEGACY_GAP_DOMAIN_MODULES: tuple[str, ...] = (
    "app.fastapi_routes.domains.conversation.conversation_routes",
    "app.fastapi_routes.domains.excel.excel_routes",
    "app.fastapi_routes.domains.product.product_routes",
    "app.fastapi_routes.domains.static.static_routes",
    "app.fastapi_routes.domains.system.system_routes",
    "app.fastapi_routes.domains.shipment.shipment_routes",
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
