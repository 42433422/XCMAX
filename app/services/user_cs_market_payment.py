"""客服到款：查询 MODstore 权威订单（Java PostgreSQL 或 Python JSON）。"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def _market_base_url() -> str:
    return (os.environ.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:8765").strip().rstrip("/")


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def fetch_payment_summary_for_cs(
    market_user_id: int,
    *,
    min_amount_cents: Optional[int] = None,
    expected_out_trade_no: str = "",
) -> dict[str, Any]:
    """调用 MODstore ``GET /api/internal/payment/summary``。"""
    key = _internal_api_key()
    if not key:
        return {
            "ok": False,
            "payment_verified": False,
            "error": "未配置 XCAGI_MARKET_INTERNAL_API_KEY",
            "matched_order": None,
            "paid_orders": [],
        }
    params: dict[str, Any] = {"market_user_id": int(market_user_id)}
    if min_amount_cents is not None:
        params["min_amount_cents"] = int(min_amount_cents)
    if expected_out_trade_no:
        params["expected_out_trade_no"] = expected_out_trade_no.strip()
    url = f"{_market_base_url()}/api/internal/payment/summary"
    try:
        with httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
            resp = client.get(
                url,
                params=params,
                headers={"x-internal-api-key": key},
            )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "payment_verified": False,
                "error": f"market {resp.status_code}: {resp.text[:240]}",
                "matched_order": None,
                "paid_orders": [],
            }
        data = resp.json()
        if not isinstance(data, dict):
            return {"ok": False, "payment_verified": False, "error": "invalid response"}
        return {
            "ok": bool(data.get("ok", True)),
            "payment_verified": bool(data.get("payment_verified")),
            "matched_order": data.get("matched_order"),
            "paid_orders": data.get("paid_orders") or [],
            "source": data.get("source"),
            "error": "",
        }
    except Exception as exc:
        logger.exception("fetch_payment_summary_for_cs uid=%s", market_user_id)
        return {
            "ok": False,
            "payment_verified": False,
            "error": str(exc)[:300],
            "matched_order": None,
            "paid_orders": [],
        }
