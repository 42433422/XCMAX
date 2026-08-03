"""Live account projections shared by the market account HTTP adapter."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any


def bootstrap_overview_needs_live_merge(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return True
    return not (
        isinstance(data.get("user"), dict)
        and isinstance(data.get("wallet"), dict)
        and (isinstance(data.get("membership"), dict) or isinstance(data.get("plan"), dict))
    )


async def refresh_overview_wallet(
    data: dict[str, Any],
    authorization: str,
    sync_warning: str,
    *,
    proxy_json: Callable[..., Awaitable[Any]],
    error_message: Callable[[Any, int], str],
) -> str:
    """Replace bootstrap wallet data with a live snapshot or an explicit unknown value."""
    snapshot: dict[str, Any] = {}
    warning = ""
    for path in ("/api/wallet/overview", "/api/wallet/balance"):
        payload = await proxy_json(
            "GET", path, authorization=authorization, return_error_payload=True
        )
        if isinstance(payload, dict) and not payload.get("__proxy_error__"):
            raw = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            wallet = raw.get("wallet") if isinstance(raw.get("wallet"), dict) else raw
            if isinstance(wallet, dict):
                snapshot.update(wallet)
        elif not warning and isinstance(payload, dict) and payload.get("__proxy_error__"):
            warning = error_message(payload.get("payload"), int(payload.get("status_code") or 502))
    if "balance" in snapshot:
        data["wallet"] = snapshot
    else:
        data["wallet"] = {"balance": None}
        sync_warning = sync_warning or warning or "市场钱包实时余额未同步"
    return sync_warning


def degraded_llm_catalog(response: Any, market_base_url: str) -> dict[str, Any]:
    try:
        raw = json.loads(response.body.decode() if response.body else "{}")
        message = str(raw.get("message") or raw.get("detail") or "模型目录暂时不可用")
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        message = "模型目录暂时不可用"
    return {
        "success": True,
        "data": {
            "degraded": True,
            "providers": [],
            "sync_warning": message,
            "market_base_url": market_base_url,
        },
    }
