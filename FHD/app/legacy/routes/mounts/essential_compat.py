"""Route mount: essential_compat."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.legacy.routes.legacy_compat import _import_and_mount
from app.legacy.routes.openapi_route_compat import iter_effective_routes
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _has_route(app: FastAPI, path: str) -> bool:
    return any(route.path == path for route in iter_effective_routes(app.routes))


def _ensure_auth_session_validate_route(app: FastAPI) -> None:
    if _has_route(app, "/api/auth/session/validate"):
        return

    @app.get("/api/auth/session/validate")
    async def auth_session_validate_essential(_request: Request):
        return JSONResponse(
            {
                "success": False,
                "valid": False,
                "error": {"code": "NO_SESSION", "message": "无会话信息"},
            },
            status_code=200,
        )

    logger.info("Registered auth_session_validate fallback (essential compat)")


def register_essential_compat_routes(app: FastAPI) -> None:
    """CI/E2E 在跳过完整 legacy 栈时仍须可用的最小 API（避免 payment_sot 等重依赖）。"""
    try:
        _import_and_mount(app, "app.fastapi_routes.domains.auth.auth_routes", "router", "")
        logger.info("Registered legacy_auth_router (essential compat, /api/auth/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential auth routes skipped: %s", e)
    _ensure_auth_session_validate_route(app)

    try:
        _import_and_mount(app, "app.fastapi_routes.system_routes", "router", "")
        logger.info("Registered system_router (essential compat, /api/system/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential system routes skipped: %s", e)

    try:
        _import_and_mount(app, "app.fastapi_routes.tools_execute", "router", "")
        logger.info("Registered tools_execute (essential, /api/tools/execute)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential tools_execute skipped: %s", e)

    try:
        _import_and_mount(app, "app.fastapi_routes.agent_tool_lifecycle", "router", "")
        logger.info("Registered agent tool lifecycle (/api/agent-tools)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential agent tool lifecycle skipped: %s", e)

    try:
        _import_and_mount(app, "app.legacy.routes.product.compat_routes", "router", "/api")
        logger.info("Registered product compat (essential, /api/products/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential product compat skipped: %s", e)
