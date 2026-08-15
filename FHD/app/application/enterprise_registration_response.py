"""Safe response builders for enterprise registration handoff."""

from __future__ import annotations

from typing import Any


def pending_registration_payload(
    market_registration: dict[str, Any],
) -> dict[str, Any]:
    """Build the desktop-to-market purchase handoff without local provisioning."""

    market_base = str(market_registration.get("market_base_url") or "").rstrip("/")
    purchase_path = "/market/account-plans?plan=saas-trial-30&source=xcagi-desktop"
    purchase_url = (
        f"{market_base}/account-plans?plan=saas-trial-30&source=xcagi-desktop"
        if market_base
        else purchase_path
    )
    return {
        "success": True,
        "registered": True,
        "account_state": str(market_registration.get("account_state") or "pending_plan"),
        "next_action": str(market_registration.get("next_action") or "select_plan"),
        "desktop_access": False,
        "purchase_url": purchase_url,
        "market_access_token": str(market_registration.get("token") or ""),
        "market_refresh_token": str(market_registration.get("refresh_token") or ""),
        "market_user_id": market_registration.get("market_user_id"),
    }
