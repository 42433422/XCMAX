"""Route mount: lan."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.fastapi_routes._route_helpers import import_and_mount as _import_and_mount
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def register_lan_routes(app: FastAPI) -> None:
    """注册局域网授权用户端 + 管理员路由（/api/lan/*）。"""
    try:
        _import_and_mount(app, "app.fastapi_routes.lan_routes", "router", "")
        logger.info("Registered LAN routes (/api/lan/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("LAN routes skipped: %s", e)

    try:
        _import_and_mount(app, "app.fastapi_routes.lan_admin_routes", "router", "")
        logger.info("Registered LAN admin routes (/api/lan/admin/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("LAN admin routes skipped: %s", e)

    # Settings are served by lan_admin_routes, preserving the existing
    # host-only authority and response contract. The alternative settings
    # module remains available to SDK callers, but is not mounted twice.
