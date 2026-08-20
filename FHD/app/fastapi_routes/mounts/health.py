"""Route mount: health."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.build_identity import build_identity
from app.runtime_integrity import neuro_degraded_reasons, runtime_integrity_snapshot
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def register_health_routes(app: FastAPI) -> None:
    """注册健康检查路由"""

    @app.get("/api/health", tags=["health"])
    async def health_check(lite: bool = False):
        runtime = runtime_integrity_snapshot(app)
        payload: dict = {
            "status": runtime["status"],
            "version": app.version,
            "service": "xcagi-fastapi",
            "runtime": runtime,
            "degradedReasons": list(runtime["degraded_reasons"]),
            "build": build_identity(),
        }
        if lite:
            return payload
        try:
            from app.neuro_bus.integrations.fastapi_integration import get_neurobus_health
            from app.neuro_bus.integrations.intent_integration import is_neuro_stack_enabled

            if is_neuro_stack_enabled():
                payload["neuro"] = get_neurobus_health()
            else:
                payload["neuro"] = {"enabled": False}
        except RECOVERABLE_ERRORS:
            logger.exception("neuro health snapshot failed")
            payload["neuro"] = {"enabled": True, "error": "unavailable"}
        neuro_reasons = neuro_degraded_reasons(payload.get("neuro"))
        if neuro_reasons:
            payload["degradedReasons"].extend(neuro_reasons)
            if payload["status"] == "healthy":
                payload["status"] = "degraded"
        return payload

    @app.get("/api/ping", tags=["health"])
    async def ping():
        return {"pong": True}

    logger.info("Registered health check routes")
