"""Route mount: infrastructure (desktop, GDPR)."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


def register_infrastructure_routes(app: FastAPI) -> None:
    """Register desktop runtime and GDPR routes."""
    try:
        from app.fastapi_routes.desktop_runtime import router as desktop_runtime_router

        app.include_router(desktop_runtime_router)
        logger.info("Registered desktop_runtime_router (/api/desktop/*)")
    except OPERATIONAL_ERRORS as e:
        logger.warning("Desktop runtime routes skipped: %s", e)
    try:
        from app.fastapi_routes.desktop_automation import router as desktop_automation_router

        app.include_router(desktop_automation_router)
        logger.info("Registered desktop_automation_router (/api/desktop/automation/*)")
    except OPERATIONAL_ERRORS as e:
        logger.warning("Desktop automation routes skipped: %s", e)
    try:
        from app.fastapi_routes.gdpr import router as gdpr_router

        app.include_router(gdpr_router)
        logger.info("Registered gdpr_router (/api/gdpr/*)")
    except OPERATIONAL_ERRORS as e:
        logger.warning("GDPR routes skipped: %s", e)
