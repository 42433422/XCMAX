"""考勤行业包 — FastAPI 占位路由（通用行业能力；转换见 taiyangniao-pro）。"""

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
                "message": "attendance-industry generic pack; install account custom mod for conversion",
            }
        )

    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info("Mod %s FastAPI routes registered (industry stub)", mod_id)


def mod_init():
    logger.info("Mod attendance-industry initialized")
