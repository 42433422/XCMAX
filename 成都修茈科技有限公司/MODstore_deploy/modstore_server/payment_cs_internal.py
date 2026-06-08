"""客服/CRM 服务间支付查询：统一走 Java SoT 或 Python JSON（与 PAYMENT_BACKEND 一致）。"""

from __future__ import annotations

import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx

from modstore_server import payment_orders
from modstore_server.application.payment_gateway import PaymentGatewayService

logger = logging.getLogger(__name__)


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or ""
    ).strip()


def _amount_to_cents(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    try:
        yuan = Decimal(str(raw).strip().replace(",", ""))
        return int((yuan * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None


def fetch_user_orders_for_cs(
    market_user_id: int,
    *,
    status: Optional[str] = "paid",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """按 market user_id 拉取订单列表（Java PostgreSQL 或本地 JSON）。"""
    uid = int(market_user_id)
    gw = PaymentGatewayService()
    if gw.backend == "java":
        key = _internal_api_key()
        if not key:
            return {
                "ok": False,
                "message": "internal api key not configured",
                "orders": [],
                "total": 0,
                "source": "java_postgresql",
            }
        params: dict[str, Any] = {"user_id": uid, "limit": limit, "offset": offset}
        if status:
            params["status"] = status
        url = f"{gw.target_base_url()}/api/internal/payment/user-orders"
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                resp = client.get(
                    url,
                    params=params,
                    headers={"X-Internal-Api-Key": key},
                )
            if resp.status_code >= 400:
                return {
                    "ok": False,
                    "message": f"java payment {resp.status_code}: {resp.text[:200]}",
                    "orders": [],
                    "total": 0,
                    "source": "java_postgresql",
                }
            data = resp.json()
            if not isinstance(data, dict):
                return {"ok": False, "message": "invalid java response", "orders": [], "total": 0}
            return {
                "ok": bool(data.get("ok", True)),
                "orders": list(data.get("orders") or []),
                "total": int(data.get("total") or 0),
                "source": "java_postgresql",
            }
        except Exception as exc:
            logger.exception("fetch_user_orders_for_cs java failed uid=%s", uid)
            return {
                "ok": False,
                "message": str(exc)[:300],
                "orders": [],
                "total": 0,
                "source": "java_postgresql",
            }

    rows, total = payment_orders.list_orders(
        user_id=uid,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "ok": True,
        "orders": rows,
        "total": total,
        "source": "python_json",
    }


def find_matching_paid_order(
    market_user_id: int,
    *,
    expected_out_trade_no: str = "",
    min_amount_cents: Optional[int] = None,
    amount_tolerance_cents: int = 1,
) -> Optional[dict[str, Any]]:
    """在权威订单库中查找已支付订单（按单号或金额匹配）。"""
    out_no = (expected_out_trade_no or "").strip()
    if out_no:
        gw = PaymentGatewayService()
        if gw.backend == "java":
            summary = fetch_user_orders_for_cs(market_user_id, status=None, limit=100)
            for row in summary.get("orders") or []:
                if (
                    str(row.get("out_trade_no") or "") == out_no
                    and str(row.get("status") or "") == "paid"
                ):
                    return row
        else:
            doc = payment_orders.find(out_no)
            if doc and str(doc.get("status") or "") == "paid":
                if int(doc.get("user_id") or 0) in (0, int(market_user_id)):
                    return doc
        return None

    summary = fetch_user_orders_for_cs(market_user_id, status="paid", limit=50)
    if not summary.get("ok"):
        return None
    candidates = list(summary.get("orders") or [])
    if min_amount_cents is None:
        return candidates[0] if candidates else None

    target = int(min_amount_cents)
    tol = max(0, int(amount_tolerance_cents))
    for row in candidates:
        cents = _amount_to_cents(row.get("total_amount"))
        if cents is not None and abs(cents - target) <= tol:
            return row
    return None


def payment_summary_for_cs(
    market_user_id: int,
    *,
    min_amount_cents: Optional[int] = None,
    expected_out_trade_no: str = "",
) -> dict[str, Any]:
    """供 FHD 客服到款核对的聚合结果。"""
    match = find_matching_paid_order(
        market_user_id,
        expected_out_trade_no=expected_out_trade_no,
        min_amount_cents=min_amount_cents,
    )
    paid_list = fetch_user_orders_for_cs(market_user_id, status="paid", limit=20)
    return {
        "ok": True,
        "source": paid_list.get("source") or "unknown",
        "paid_orders": paid_list.get("orders") or [],
        "paid_total": paid_list.get("total") or 0,
        "matched_order": match,
        "payment_verified": match is not None,
    }
