"""将人员 / 客户 / yuangon 同步路由挂到 ``/api/mod/xcmax-personnel``。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


def register_fastapi_routes(app: FastAPI, mod_id: str) -> None:
    from app.mod_sdk.personnel_http import attach_personnel_crud_routes

    router = APIRouter(tags=[f"mod-{mod_id}"])
    attach_personnel_crud_routes(router, mod_id)
    app.include_router(router, prefix=f"/api/mods/{mod_id}")
    app.include_router(router, prefix=f"/api/mod/{mod_id}")
    logger.info("xcmax-personnel: personnel CRUD at /api/mod/%s/*", mod_id)
