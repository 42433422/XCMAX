"""__MOD_NAME__ — FastAPI 路由（与 ModManager ``register_fastapi_routes`` 约定一致；无 Flask）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"mod-{mod_id}"])

    @router.get("/hello")
    async def hello():
        return {
            "success": True,
            "data": {"message": f"Hello from {mod_id}", "mod": "__MOD_ID__"},
        }

    app.include_router(router)
    logger.info("Mod skeleton FastAPI routes registered: %s", mod_id)


def mod_init():
    logger.info("Mod __MOD_ID__ initialized")
