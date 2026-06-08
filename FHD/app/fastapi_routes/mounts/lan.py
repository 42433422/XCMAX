"""Route mount: lan."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

def register_lan_routes(app: FastAPI) -> None:
    """注册局域网授权用户端 + 管理员路由（/api/lan/*）。"""
    try:
        from app.fastapi_routes.lan_routes import router as lan_router

        app.include_router(lan_router)
        logger.info("Registered LAN routes (/api/lan/*)")
    except Exception as e:
        logger.warning("LAN routes skipped: %s", e)

    try:
        from app.fastapi_routes.lan_admin_routes import router as lan_admin_router

        app.include_router(lan_admin_router)
        logger.info("Registered LAN admin routes (/api/lan/admin/*)")
    except Exception as e:
        logger.warning("LAN admin routes skipped: %s", e)

    try:
        from app.fastapi_routes.lan_settings_routes import router as lan_settings_router

        app.include_router(lan_settings_router)
        logger.info("Registered LAN settings routes (/api/lan/admin/settings)")
    except Exception as e:
        logger.warning("LAN settings routes skipped: %s", e)


