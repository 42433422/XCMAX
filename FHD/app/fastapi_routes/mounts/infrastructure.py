"""Route mount: infrastructure (desktop, GDPR)."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.runtime_integrity import record_runtime_component
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def register_infrastructure_routes(app: FastAPI) -> None:
    """Register desktop runtime and GDPR routes."""
    try:
        from app.fastapi_routes.kellai_binding import router as kellai_binding_router

        app.include_router(kellai_binding_router)
        logger.info("Registered kellai_binding_router (/api/kellai/binding/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("客来来绑定路由 skipped: %s", e)
    try:
        from app.fastapi_routes.desktop_runtime import router as desktop_runtime_router

        app.include_router(desktop_runtime_router)
        record_runtime_component(app, "desktop_runtime_routes", ok=True, required=True)
        logger.info("Registered desktop_runtime_router (/api/desktop/*)")
    except RECOVERABLE_ERRORS as e:
        record_runtime_component(
            app, "desktop_runtime_routes", ok=False, required=True, detail=str(e)
        )
        logger.warning("Desktop runtime routes skipped: %s", e)
    try:
        from app.fastapi_routes.gdpr import router as gdpr_router

        app.include_router(gdpr_router)
        record_runtime_component(app, "gdpr_routes", ok=True)
        logger.info("Registered gdpr_router (/api/gdpr/*)")
    except RECOVERABLE_ERRORS as e:
        record_runtime_component(app, "gdpr_routes", ok=False, detail=str(e))
        logger.warning("GDPR routes skipped: %s", e)
