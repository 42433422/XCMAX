"""Route mount: health."""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)

def register_health_routes(app: FastAPI) -> None:
    """注册健康检查路由"""

    @app.get("/api/health", tags=["health"])
    async def health_check():
        payload: dict = {
            "status": "healthy",
            "version": "1.0.0",
            "service": "xcagi-fastapi",
        }
        try:
            from app.neuro_bus.integrations.fastapi_integration import get_neurobus_health
            from app.neuro_bus.integrations.intent_integration import is_neuro_stack_enabled

            if is_neuro_stack_enabled():
                payload["neuro"] = get_neurobus_health()
            else:
                payload["neuro"] = {"enabled": False}
        except OPERATIONAL_ERRORS as exc:
            payload["neuro"] = {"enabled": True, "error": str(exc)}
        return payload

    @app.get("/api/ping", tags=["health"])
    async def ping():
        return {"pong": True}

    logger.info("Registered health check routes")


