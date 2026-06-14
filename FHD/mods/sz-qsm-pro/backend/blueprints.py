"""奇士美 PRO — FastAPI 路由（涂料定制 + phone-agent 占位）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_PHONE_RUNNING = False


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter()

    @router.get("/status")
    async def status():
        return JSONResponse(
            {
                "success": True,
                "mod_id": mod_id,
                "message": "sz-qsm-pro scaffold; install full .xcmod for production features",
            }
        )

    phone_router = APIRouter()

    @phone_router.get("/status")
    async def phone_agent_status():
        return JSONResponse(
            {
                "success": True,
                "mod_id": mod_id,
                "running": _PHONE_RUNNING,
                "stub": True,
            }
        )

    @phone_router.post("/start")
    async def phone_agent_start():
        global _PHONE_RUNNING
        _PHONE_RUNNING = True
        return JSONResponse({"success": True, "running": True, "stub": True})

    @phone_router.post("/stop")
    async def phone_agent_stop():
        global _PHONE_RUNNING
        _PHONE_RUNNING = False
        return JSONResponse({"success": True, "running": False, "stub": True})

    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    app.include_router(phone_router, prefix=f"/api/mod/{mod_id}/phone-agent")
    logger.info(
        "Mod %s FastAPI routes: /api/mod/%s/* and phone-agent",
        mod_id,
        mod_id,
    )


def mod_init():
    logger.info("Mod sz-qsm-pro initialized (scaffold)")
