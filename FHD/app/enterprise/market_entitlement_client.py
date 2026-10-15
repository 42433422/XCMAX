"""Market entitlement response parsing and retrieval, independent of session state."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import Any

from app.mod_sdk.platform_shell import PROTECTED_CLIENT_MOD_IDS

logger = logging.getLogger(__name__)


def _market_user_id_from_access_token(market_token: str) -> int | None:
    """Best-effort identity fallback for market JWTs already accepted by market APIs."""
    token = (market_token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
        raw = data.get("sub")
        return int(raw) if raw is not None and str(raw).strip() else None
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def parse_mod_ids_from_market_payload(
    payload: Any, *, is_client_mod_id: Callable[[str], bool] | None = None
) -> set[str]:
    if is_client_mod_id is None:
        is_client_mod_id = PROTECTED_CLIENT_MOD_IDS.__contains__
    ids: set[str] = set()
    if not isinstance(payload, dict):
        return ids
    raw_ids = payload.get("mod_ids")
    if isinstance(raw_ids, list):
        for mid in raw_ids:
            s = str(mid).strip()
            if s and is_client_mod_id(s):
                ids.add(s)
        if ids:
            return ids
    data = payload.get("data")
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and isinstance(data.get("mods"), list):
        rows = data["mods"]
    else:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if mid:
            ids.add(mid)
    return ids


async def fetch_entitled_client_mod_ids_from_market(market_token: str) -> set[str]:
    """从修茈市场拉取当前账号绑定的客户 Mod（不走 is_admin 全量列表）。"""
    from app.application.delivery_entitlements import valid_entitlement_ids
    from app.fastapi_routes.market_account import _proxy_json

    tok = (market_token or "").strip()
    if not tok:
        return set()
    auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    payload = await _proxy_json(
        "GET",
        "/api/enterprise/entitled-mod-ids",
        authorization=auth,
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        logger.warning("fetch entitled-mod-ids failed: %s", payload)
        return set()
    if isinstance(payload, dict):
        raw = payload.get("mod_ids") or payload.get("data", {}).get("mod_ids")
        if isinstance(raw, list):
            return valid_entitlement_ids(raw)
    return parse_mod_ids_from_market_payload(payload)


async def fetch_entitled_client_mod_ids_for_market_user(
    market_token: str,
    target_market_user_id: int,
) -> set[str]:
    """管理员代管：拉取指定市场用户的 user_mods 客户 Mod。"""
    from app.fastapi_routes.market_account import _proxy_json

    tok = (market_token or "").strip()
    if not tok:
        return set()
    auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    payload = await _proxy_json(
        "GET",
        f"/api/admin/users/{int(target_market_user_id)}/mods",
        authorization=auth,
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        logger.warning("fetch admin user mods failed: %s", payload)
        return set()
    return parse_mod_ids_from_market_payload(payload)
