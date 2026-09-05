"""Refresh verified delivery rights into the requesting session only."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from app.application.private_mod_delivery_artifacts import custom_delivery_remote_json
from app.application.session_account_meta import load_session_account_meta
from app.enterprise.private_delivery_binding import (
    load_session_private_delivery_binding,
)
from app.infrastructure.auth.dependencies import session_id_from_request
from app.mod_sdk.owner_workspace import authenticated_owner
from app.utils.operational_errors import RECOVERABLE_ERRORS

_REFRESH_ERRORS: tuple[type[Exception], ...] = RECOVERABLE_ERRORS + (HTTPException,)


def valid_entitlement_ids(values: list) -> set[str]:
    """IDs from the authenticated account API can include newly generated Mods."""
    return {
        value
        for value in values
        if isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", value)
    }


def _persist(session_id: str, market_user_id: int, ids: set[str]) -> bool:
    from app.db.models.user import Session as UserSession
    from app.enterprise.mod_entitlements import _session_row_db_context

    with _session_row_db_context() as db:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        if (
            row is None
            or row.market_user_id != market_user_id
            or row.impersonating_market_user_id
            or row.impersonating_username
        ):
            return False
        expires = row.expires_at
        if expires.replace(tzinfo=expires.tzinfo or UTC) <= datetime.now(UTC):
            return False
        row.entitled_mod_ids_json = json.dumps(sorted(ids), ensure_ascii=False)
        db.commit()
    return True


async def refresh_delivery_entitlements(request: Request, market_token: str) -> bool:
    """Network failures retain existing rights; account changes discard late results."""
    try:
        owner = authenticated_owner(request)
        sid = session_id_from_request(request)
        meta = load_session_account_meta(sid) or {}
        if meta.get("impersonating_market_user_id") or meta.get("impersonating_username"):
            return False
        binding = load_session_private_delivery_binding(sid)
        market = int(binding.get("market_user_id") or 0)
        if not sid or market <= 0 or not market_token:
            return False
        async with asyncio.timeout(5):
            payload = await custom_delivery_remote_json(
                market_token, "/api/enterprise/entitled-mod-ids"
            )
        raw = payload.get("mod_ids")
        if (
            payload.get("ok") is not True
            or payload.get("user_id") != market
            or not isinstance(raw, list)
        ):
            return False
        if authenticated_owner(request) != owner:
            return False
        if load_session_private_delivery_binding(sid).get("market_user_id") != market:
            return False
        return _persist(sid, market, valid_entitlement_ids(raw))
    except _REFRESH_ERRORS:
        return False
