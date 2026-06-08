"""Route mount: essential_compat."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

def register_essential_compat_routes(app: FastAPI) -> None:
    """CI/E2E 在跳过完整 legacy 栈时仍须可用的最小 API（避免 payment_sot 等重依赖）。"""
    try:
        from app.fastapi_routes.system_routes import router as system_router

        app.include_router(system_router)
        logger.info("Registered system_router (essential compat, /api/system/*)")
    except Exception as e:
        logger.warning("essential system routes skipped: %s", e)

    try:
        from app.fastapi_routes.domains.product.compat_routes import router as product_compat_router

        app.include_router(product_compat_router, prefix="/api")
        logger.info("Registered product compat (essential, /api/products/*)")
    except Exception as e:
        logger.warning("essential product compat skipped: %s", e)


