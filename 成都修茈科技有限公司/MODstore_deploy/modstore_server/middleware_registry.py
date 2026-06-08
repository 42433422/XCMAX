from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from modstore_server.api.middleware import (
    market_history_spa_middleware,
    payment_backend_proxy_middleware,
    request_id_middleware,
)


def _validate_production_secrets():
    """拒绝空 JWT 密钥启动，除非显式 ``MODSTORE_INSECURE_EMPTY_JWT=1``（仅本地一次性脚本）。"""
    env = os.environ.get("MODSTORE_ENV", "development")
    secret = (os.environ.get("MODSTORE_JWT_SECRET") or "").strip()
    insecure = (os.environ.get("MODSTORE_INSECURE_EMPTY_JWT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if not secret:
        if insecure:
            logging.getLogger(__name__).error(
                "MODSTORE_JWT_SECRET is empty but MODSTORE_INSECURE_EMPTY_JWT is set — "
                "JWT signing is insecure; do not use in production."
            )
            return
        raise RuntimeError(
            "MODSTORE_JWT_SECRET must be set to a non-empty value. "
            "For local throwaway scripts only, set MODSTORE_INSECURE_EMPTY_JWT=1 (not for production)."
        )

    if env == "production" and len(secret) < 32:
        raise RuntimeError(
            "MODSTORE_JWT_SECRET must be set and at least 32 characters in production"
        )


def _get_allowed_origins() -> list[str]:
    env = os.environ.get("CORS_ORIGINS", "").strip()
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://127.0.0.1:5176",
        "http://localhost:5176",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "https://xiu-ci.com",
        "https://www.xiu-ci.com",
    ]


def _get_cors_origin_regex() -> str | None:
    raw = os.environ.get("CORS_ORIGIN_REGEX", "").strip()
    if raw:
        low = raw.lower()
        if low in ("0", "false", "none", "-"):
            return None
        return raw
    return r"^https://[a-zA-Z0-9.-]+\.edgeone\.cool$"


def register_all_middleware(app: FastAPI) -> None:
    _validate_production_secrets()

    from modstore_server.api.csrf import CSRFMiddleware
    from modstore_server.api.rate_limiter import RateLimiterMiddleware
    from modstore_server.api.security_headers import SecurityHeadersMiddleware
    from modstore_server.api.xss_sanitizer import XSSSanitizerMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(XSSSanitizerMiddleware)
    app.add_middleware(RateLimiterMiddleware)

    @app.middleware("http")
    async def _request_id_mw(request: Request, call_next):
        return await request_id_middleware(request, call_next)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_origin_regex=_get_cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _payment_backend_proxy_mw(request: Request, call_next):
        return await payment_backend_proxy_middleware(request, call_next)

    @app.middleware("http")
    async def _market_history_spa_mw(request: Request, call_next):
        return await market_history_spa_middleware(request, call_next)
