"""Route mount: neuro_migration."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

def register_neuro_migration_routes(app: FastAPI) -> None:
    try:
        from app.fastapi_routes.neuro_migration_routes import router as neuro_migration_router

        app.include_router(neuro_migration_router)
        logger.info("Registered neuro migration routes (/api/neuro/*)")
    except Exception as e:
        logger.warning("Neuro migration routes skipped: %s", e)


