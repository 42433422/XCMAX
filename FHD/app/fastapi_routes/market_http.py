"""HTTP transport helpers for the official market account bridge.

Keeping these lifecycle and connection-pool concerns outside the route module
lets the account API remain focused on request/response policy.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
from collections.abc import Callable
from hashlib import sha256
from urllib.parse import urlparse

import httpx

OFFICIAL_MARKET_HOSTS = frozenset({"xiu-ci.com", "www.xiu-ci.com"})
MARKET_READ_CLIENTS: dict[tuple[int, str], httpx.AsyncClient] = {}
_MARKET_READ_CACHE_KEY = secrets.token_bytes(32)


def market_http_timeout() -> float:
    try:
        return float(os.environ.get("XCAGI_MARKET_HTTP_TIMEOUT", "20"))
    except ValueError:
        return 20.0


def market_auth_timeout() -> float:
    """Bound interactive sign-in separately from slower market data reads."""
    try:
        return max(3.0, float(os.environ.get("XCAGI_MARKET_AUTH_TIMEOUT", "8")))
    except ValueError:
        return 8.0


def market_internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def is_official_market_base(base_url: str) -> bool:
    try:
        return (urlparse(base_url).hostname or "").lower() in OFFICIAL_MARKET_HOSTS
    except ValueError:
        return False


def market_read_client(
    authorization: str,
    timeout: float,
    normalize_authorization: Callable[[str], str],
) -> httpx.AsyncClient:
    """Reuse a TLS connection per event loop and credential digest for safe reads."""
    loop = asyncio.get_running_loop()
    # This is an in-memory connection-pool key, not credential storage. A
    # process-local random HMAC key prevents the authorization value from being
    # recoverable from the pool key without adding password-hashing work to the
    # interactive official-account path.
    credential_key = hmac.new(
        _MARKET_READ_CACHE_KEY,
        normalize_authorization(authorization).encode("utf-8"),
        sha256,
    ).hexdigest()
    key = (id(loop), credential_key)
    client = MARKET_READ_CLIENTS.get(key)
    if client is not None and not client.is_closed:
        return client
    client = httpx.AsyncClient(
        timeout=timeout,
        trust_env=False,
        limits=httpx.Limits(
            max_connections=4,
            max_keepalive_connections=2,
            keepalive_expiry=45.0,
        ),
    )
    MARKET_READ_CLIENTS[key] = client
    return client


async def close_market_read_clients() -> None:
    """Release pooled official-market connections during local backend shutdown."""
    clients = tuple(MARKET_READ_CLIENTS.values())
    MARKET_READ_CLIENTS.clear()
    if clients:
        await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)
