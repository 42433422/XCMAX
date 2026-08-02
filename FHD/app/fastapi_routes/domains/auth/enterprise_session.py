"""Desktop-specific official-market session coordination.

The local desktop can paint from an already verified persisted session while
the official account and entitlement refresh continues in the background.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _desktop_runtime_active() -> bool:
    return os.environ.get("XCAGI_DESKTOP_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


async def _refresh_official_market_session(session_id: str) -> None:
    try:
        from app.enterprise.mod_entitlements import sync_entitlements_for_session
        from app.fastapi_routes.market_account import resolve_valid_market_access_token

        if not await resolve_valid_market_access_token(session_id):
            logger.warning("desktop session has no valid official market token after refresh")
            return
        await sync_entitlements_for_session(session_id)
    except Exception:  # noqa: BLE001 - detached refresh cannot crash the local backend
        logger.exception("desktop enterprise session background refresh failed")


def _schedule_official_market_session_refresh(session_id: str) -> None:
    asyncio.create_task(
        _refresh_official_market_session(session_id),
        name="xcagi-enterprise-session-refresh",
    )


async def market_session_mode(
    session_id: str, *, schedule_refresh: Callable[[str], None] | None = None
) -> str:
    """Return ``desktop``, ``online``, ``missing``, or empty for non-enterprise."""
    from app.mod_sdk.product_skus import resolve_product_sku

    if resolve_product_sku() != "enterprise":
        return ""
    from app.fastapi_routes.market_account import (
        resolve_valid_market_access_token,
        session_market_token,
    )

    if _desktop_runtime_active():
        if not session_market_token(session_id):
            return "missing"
        (schedule_refresh or _schedule_official_market_session_refresh)(session_id)
        return "desktop"
    return "online" if await resolve_valid_market_access_token(session_id) else "missing"


async def entitled_mod_ids_for_session(
    session_id: str, *, desktop_refresh_pending: bool
) -> list[str]:
    from app.enterprise.mod_entitlements import (
        get_cached_entitled_client_mod_ids,
        restore_entitlements_from_session_row,
        sync_entitlements_for_session,
    )

    if desktop_refresh_pending:
        restore_entitlements_from_session_row(session_id)
        cached = get_cached_entitled_client_mod_ids()
        return sorted(cached) if cached is not None else []
    entitled = await sync_entitlements_for_session(session_id)
    if entitled:
        return sorted(entitled)
    cached = get_cached_entitled_client_mod_ids()
    return sorted(cached) if cached is not None else []
