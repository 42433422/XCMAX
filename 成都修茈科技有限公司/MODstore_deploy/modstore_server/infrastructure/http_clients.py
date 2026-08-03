"""Process-wide shared httpx client pools.

Using module-level singletons avoids creating/destroying TCP connections on
every request. Timeouts MUST be passed per-request (``timeout=`` argument) so
that different operations can use appropriate deadlines without splitting the
connection pool.

Async clients (for ``async def`` handlers):
  - :func:`get_java_client`     — Python → Java payment service
  - :func:`get_external_client` — external API calls (LLM providers, research,
                                  embeddings, etc.)

Sync client (for ``def`` handlers / sync utilities):
  - :func:`get_java_sync_client` — used by java_me_profile.fetch_java_user_overlay

Call :func:`close_all` from the FastAPI shutdown lifespan to drain connections
gracefully.
"""

from __future__ import annotations

import httpx

# ---------------------------------------------------------------------------
# Async clients
# ---------------------------------------------------------------------------

_java_async_client: httpx.AsyncClient | None = None
_external_async_client: httpx.AsyncClient | None = None

_POOL_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=200)


def get_java_client() -> httpx.AsyncClient:
    """Shared async client for calls to the Java payment microservice."""
    global _java_async_client
    if _java_async_client is None:
        _java_async_client = httpx.AsyncClient(limits=_POOL_LIMITS)
    return _java_async_client


def get_external_client() -> httpx.AsyncClient:
    """Shared async client for external API calls (LLM providers, search, embeddings)."""
    global _external_async_client
    if _external_async_client is None:
        _external_async_client = httpx.AsyncClient(limits=_POOL_LIMITS)
    return _external_async_client


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------

_java_sync_client: httpx.Client | None = None


def get_java_sync_client() -> httpx.Client:
    """Shared sync client for blocking calls to the Java payment microservice.

    Safe to call from ``def`` (non-async) route handlers — FastAPI runs those
    in a thread pool so blocking the calling thread is fine.
    """
    global _java_sync_client
    if _java_sync_client is None:
        _java_sync_client = httpx.Client(limits=_POOL_LIMITS)
    return _java_sync_client


# ---------------------------------------------------------------------------
# Shutdown hook
# ---------------------------------------------------------------------------


def _is_closed_event_loop(error: RuntimeError) -> bool:
    """Return whether an async client belongs to an already-destroyed loop."""
    return "event loop is closed" in str(error).lower()


async def _close_async_client(client: httpx.AsyncClient) -> None:
    """Close a pooled async client without turning a prior loop teardown into an error."""
    try:
        await client.aclose()
    except RuntimeError as error:
        # A worker can be stopped after the event loop that created an idle
        # client has already gone away.  There is nothing left to close in
        # that pool, so do not emit a false shutdown failure.  Other runtime
        # errors remain observable to the FastAPI shutdown hook.
        if not _is_closed_event_loop(error):
            raise


async def close_all() -> None:
    """Close all shared clients.  Call from the FastAPI shutdown lifespan."""
    global _java_async_client, _external_async_client, _java_sync_client

    # Detach first.  A client created on an old event loop cannot be reused,
    # even when its best-effort close encounters that loop already closing.
    java_async_client = _java_async_client
    external_async_client = _external_async_client
    java_sync_client = _java_sync_client
    _java_async_client = None
    _external_async_client = None
    _java_sync_client = None

    if java_async_client is not None:
        await _close_async_client(java_async_client)
    if external_async_client is not None:
        await _close_async_client(external_async_client)
    if java_sync_client is not None:
        java_sync_client.close()
