"""Process-wide TLS contexts for outbound httpx clients."""

from __future__ import annotations

import ssl
from functools import lru_cache

import httpx


@lru_cache(maxsize=2)
def shared_ssl_context(*, trust_env: bool = True) -> ssl.SSLContext:
    """Same verification as httpx's default, but the CA bundle is loaded once.

    Building a context per client costs tens of milliseconds of CPU, which blocks
    the event loop when done inside async routes or tight polling loops.
    """
    return httpx.create_ssl_context(trust_env=trust_env)
