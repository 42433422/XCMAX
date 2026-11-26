"""Planner Excel 组件状态；业务执行由统一能力入口提供。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"planner-excel-tools-{mod_id}"])

    @router.get("/status")
    def status():
        from app.mod_sdk.planner_native_tools import list_native_planner_tools_summary

        return {
            "success": True,
            "data": {
                "mod_id": mod_id,
                "role": "planner_capabilities",
                **list_native_planner_tools_summary(),
            },
        }

    app.include_router(router)
    logger.info("xcagi-planner-excel-tools registered: %s", mod_id)


def mod_init():
    logger.info("xcagi-planner-excel-tools mod_init")
