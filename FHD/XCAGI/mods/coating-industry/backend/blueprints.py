"""涂料行业包 — FastAPI 占位路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter()

    @router.get("/status")
    async def status():
        return JSONResponse(
            {
                "success": True,
                "mod_id": mod_id,
                "message": "coating-industry placeholder; install full .xcmod for production",
            }
        )

    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info("Mod %s FastAPI routes registered (stub)", mod_id)


def mod_init():
    logger.info("Mod coating-industry initialized (stub)")
