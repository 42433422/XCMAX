"""Route mount: essential_compat."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _has_route(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


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
        from app.fastapi_routes.domains.auth.routes import router as legacy_auth_router

        app.include_router(legacy_auth_router)
        logger.info("Registered legacy_auth_router (essential compat, /api/auth/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential auth routes skipped: %s", e)
    _ensure_auth_session_validate_route(app)

    try:
        from app.fastapi_routes.system_routes import router as system_router

        app.include_router(system_router)
        logger.info("Registered system_router (essential compat, /api/system/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential system routes skipped: %s", e)

    try:
        from app.fastapi_routes.domains.product.compat_routes import router as product_compat_router

        app.include_router(product_compat_router, prefix="/api")
        logger.info("Registered product compat (essential, /api/products/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("essential product compat skipped: %s", e)
