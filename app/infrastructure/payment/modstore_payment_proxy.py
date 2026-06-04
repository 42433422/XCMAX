"""FHD 支付请求代理至修茈市场（统一订单 SoT + 微信/支付宝）。"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def market_base_url() -> str:
    return (
        os.environ.get("XCAGI_MARKET_BASE_URL") or os.environ.get("MODSTORE_API_BASE") or ""
    ).rstrip("/")


def proxy_checkout(
    *,
    plan_id: str,
    channel: str = "alipay",
    market_user_id: int = 0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = market_base_url()
    if not base:
        return {"ok": False, "error": "XCAGI_MARKET_BASE_URL not configured"}
    url = f"{base}/api/market/payment/checkout"
    body: dict[str, Any] = {"plan_id": plan_id, "channel": channel}
    if market_user_id > 0:
        body["market_user_id"] = market_user_id
    if extra:
        body.update(extra)
    try:
        resp = httpx.post(url, json=body, timeout=20.0)
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": data.get("message") or f"HTTP {resp.status_code}",
                "raw": data,
            }
        return {"ok": True, "data": data.get("data") or data}
    except Exception as exc:
        logger.exception("modstore payment proxy failed")
        return {"ok": False, "error": str(exc)}


def wechat_checkout_redirect_url(plan_id: str, market_user_id: int = 0) -> str | None:
    """返回市场侧微信支付页 URL（宿主可 redirect）。"""
    base = market_base_url()
    if not base:
        return None
    q = f"plan_id={plan_id}&channel=wechat"
    if market_user_id > 0:
        q += f"&market_user_id={market_user_id}"
    return f"{base}/workbench/payment?{q}"
