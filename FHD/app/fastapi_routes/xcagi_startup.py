"""XCAGI 开屏与启动探测用轻量路由（与前端 App.vue pollStartupStatus 契约一致）。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["xcagi-startup"])


@router.get("/startup/status", include_in_schema=False)
@router.get("/startup/status/", include_in_schema=False)
def startup_status() -> dict:
    return {
        "ready": True,
        "progress_percent": 100,
        "components": [
            {"name": "mods", "status": "ready"},
        ],
    }
