"""Route mount: health."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy

from fastapi import FastAPI, Request, Response

from app.build_identity import build_identity
from app.runtime_integrity import merge_public_degradation, runtime_integrity_snapshot
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


async def _session_model_health(request: Request) -> dict | None:
    """Resolve this login's chat route; never generate content or borrow another login."""
    from app.infrastructure.auth.dependencies import resolve_session_user, session_id_from_request

    sid = session_id_from_request(request)
    if not sid:
        return None
    try:
        user = resolve_session_user(request)
        if user is None or not getattr(user, "is_active", True):
            return None
        from app.fastapi_routes import market_account as market

        if market._user_id_from_session(sid) != getattr(user, "id", None):
            return None
        token = market.session_market_token(sid)
        if not token:
            return {"status": "login_required"}
        result = await asyncio.wait_for(
            market._proxy_json(
                "GET",
                "/api/llm/resolve-chat-default",
                authorization=token,
                timeout=2.0,
                retries=1,
                sensitive=True,
                return_error_payload=True,
            ),
            timeout=2.5,
        )
        status = (
            result.get("status_code", 200)
            if isinstance(result, dict)
            else getattr(result, "status_code", 502)
        )
        if status in (401, 403):
            return {"status": "auth_error"}
        if status >= 500:
            return {"status": "connection_error"}
        if status >= 400 or not isinstance(result, dict) or result.get("ok") is False:
            return {"status": "configuration_error"}
        if not all(
            isinstance(result.get(key), str) and result[key].strip()
            for key in ("provider", "model")
        ):
            return {"status": "configuration_error"}
        return {"status": "configured", "completion": "not_tested"}
    except RECOVERABLE_ERRORS:
        return {"status": "connection_error"}


def register_health_routes(app: FastAPI) -> None:
    """注册健康检查路由"""

    @app.get("/api/health", tags=["health"])
    async def health_check(request: Request, response: Response, lite: bool = False):
        response.headers["Cache-Control"] = "private, no-store"
        runtime = runtime_integrity_snapshot(app)
        identity = build_identity()
        payload: dict = {
            "status": runtime["status"],
            "version": app.version,
            "service": "xcagi-fastapi",
            "runtime": runtime,
            "degradedReasons": list(runtime["degraded_reasons"]),
            "build": identity,
            "git_sha": identity["git_sha"],
            "release_id": identity["release_id"],
        }
        if lite:
            return payload
        try:
            from app.neuro_bus.integrations.fastapi_integration import get_neurobus_health
            from app.neuro_bus.integrations.intent_integration import is_neuro_stack_enabled

            if is_neuro_stack_enabled():
                payload["neuro"] = deepcopy(get_neurobus_health())
            else:
                payload["neuro"] = {"enabled": False}
        except RECOVERABLE_ERRORS:
            logger.exception("neuro health snapshot failed")
            payload["neuro"] = {"enabled": True, "error": "unavailable"}
        model_health = await _session_model_health(request)
        if model_health is not None:
            payload["sessionModel"] = model_health
            if model_health["status"] != "configured":
                payload["degradedReasons"].append("SESSION_MODEL_" + model_health["status"].upper())
                if payload["status"] == "healthy":
                    payload["status"] = "degraded"
        merge_public_degradation(payload, payload.get("neuro"))
        return payload

    @app.get("/api/ping", tags=["health"])
    async def ping():
        return {"pong": True}

    logger.info("Registered health check routes")
