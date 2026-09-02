"""饰品包装行业包 FastAPI 状态入口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter()

    @router.get("/status")
    async def status() -> dict:
        return {
            "success": True,
            "mod_id": mod_id,
            "message": "accessories-packaging industry profile active",
        }

    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info("Mod %s industry profile routes registered", mod_id)


def mod_init() -> None:
    logger.info("Mod accessories-packaging-industry initialized")
