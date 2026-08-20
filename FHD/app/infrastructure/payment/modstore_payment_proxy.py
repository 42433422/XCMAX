"""Synchronous adapter from the desktop payment bridge to MODstore's payment SOT."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import httpx


def _market_base_url() -> str:
    return (os.environ.get("XCAGI_MARKET_BASE_URL") or "").strip().rstrip("/")


def _auth_token(market_user_id: int = 0) -> str:
    raw = (
        os.environ.get("XCAGI_MARKET_AUTH_TOKEN") or os.environ.get("MODSTORE_AUTH_TOKEN") or ""
    ).strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if raw:
        return raw
    try:
        from app.fastapi_routes.market_account import latest_session_market_token

        return str(latest_session_market_token(user_id=market_user_id or None) or "").strip()
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        return ""


def _post_json(
    path: str,
    *,
    payload: dict[str, Any],
    market_user_id: int = 0,
) -> tuple[dict[str, Any] | None, str | None]:
    base = _market_base_url()
    if not base:
        return None, "XCAGI_MARKET_BASE_URL 未配置"
    token = _auth_token(market_user_id)
    if not token:
        return None, "市场账号未登录或授权令牌不可用"
    timeout = max(float(os.environ.get("MODSTORE_PAYMENT_TIMEOUT") or "10"), 1.0)
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                f"{base}{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json=payload,
            )
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return None, str(exc) or type(exc).__name__
    if response.status_code >= 400:
        if isinstance(data, dict):
            detail = data.get("message") or data.get("detail")
            return data, str(detail or f"市场支付服务返回 HTTP {response.status_code}")
        return None, f"市场支付服务返回 HTTP {response.status_code}"
    if not isinstance(data, dict):
        return None, "市场支付服务返回了非对象响应"
    return data, None


def wechat_checkout_redirect_url(plan_id: str, *, market_user_id: int = 0) -> str | None:
    """Return the public account-plan page; checkout remains authenticated in MODstore."""
    base = _market_base_url()
    normalized_plan = str(plan_id or "").strip()
    if not base or not normalized_plan:
        return None
    query: dict[str, str] = {"plan": normalized_plan, "pay_channel": "wechat"}
    if market_user_id > 0:
        query["market_user_id"] = str(market_user_id)
    return f"{base}/account-plans?{urlencode(query)}"


def proxy_checkout(
    *,
    plan_id: str,
    channel: str = "alipay",
    market_user_id: int = 0,
) -> dict[str, Any]:
    """Sign then create a checkout using the market's authenticated payment contract."""
    normalized_plan = str(plan_id or "").strip()
    if not normalized_plan:
        return {"success": False, "error": "plan_id 不能为空"}
    sign_payload, error = _post_json(
        "/api/payment/sign-checkout",
        payload={"plan_id": normalized_plan},
        market_user_id=market_user_id,
    )
    if error or sign_payload is None:
        return {"success": False, "error": error or "支付签名失败"}
    checkout_payload = {**sign_payload, "plan_id": normalized_plan}
    normalized_channel = str(channel or "alipay").strip().lower()
    if normalized_channel:
        checkout_payload["pay_channel"] = normalized_channel
    checkout, error = _post_json(
        "/api/payment/checkout",
        payload=checkout_payload,
        market_user_id=market_user_id,
    )
    if error or checkout is None:
        return {"success": False, "error": error or "市场下单失败"}
    return {"success": True, "data": checkout}


def record_market_metering(record: Any) -> dict[str, Any]:
    """Settle one legacy metering record against the market AI wallet."""
    raw = record.as_dict() if callable(getattr(record, "as_dict", None)) else record
    payload = dict(raw) if isinstance(raw, dict) else {}
    amount = str(payload.get("amount") or payload.get("amount_yuan") or "0")
    request_id = str(payload.get("idempotency_key") or payload.get("usage_key") or "").strip()
    market_user_id = int(payload.get("market_user_id") or payload.get("user_id") or 0)
    preauthorized, error = _post_json(
        "/api/wallet/ai/preauthorize",
        payload={
            "amount": amount,
            "request_id": request_id,
            "idempotency_key": f"{request_id}:preauth" if request_id else "",
            "provider": str(payload.get("provider") or ""),
            "model": str(payload.get("model") or ""),
        },
        market_user_id=market_user_id,
    )
    hold = preauthorized.get("hold") if isinstance(preauthorized, dict) else None
    hold_no = str(hold.get("hold_no") or "") if isinstance(hold, dict) else ""
    if error or not hold_no:
        return {"success": False, "error": error or "市场预授权未返回 hold_no"}
    settled, error = _post_json(
        "/api/wallet/ai/settle",
        payload={
            "hold_no": hold_no,
            "actual_amount": amount,
            "idempotency_key": f"{request_id}:settle" if request_id else f"{hold_no}:settle",
        },
        market_user_id=market_user_id,
    )
    if error or settled is None:
        return {"success": False, "error": error or "市场计量结算失败", "hold_no": hold_no}
    return {"success": True, "data": settled, "hold_no": hold_no}


__all__ = ["proxy_checkout", "record_market_metering", "wechat_checkout_redirect_url"]
