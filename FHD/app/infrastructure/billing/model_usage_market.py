"""Market-wallet HTTP integration for model usage billing."""

from __future__ import annotations

import os
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, cast

from app.infrastructure.billing import model_usage as _model_usage


def _facade() -> Any:
    return _model_usage


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _money_str(value: Any) -> str:
    return format(_facade()._money(value), "f")


def _market_amount_for_cost_units(cost_units: int) -> Decimal:
    unit = _facade()._money(os.environ.get("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT") or "0.01")
    minimum = _facade()._money(os.environ.get("MODEL_USAGE_MARKET_MIN_CHARGE") or "0.01")
    amount = _facade()._money(max(_facade()._coerce_int(cost_units), 0) * unit)
    if cost_units > 0 and amount < minimum:
        amount = minimum
    return cast(Decimal, amount)


def _market_base_url() -> str:
    return (
        (
            os.environ.get("MODEL_USAGE_MARKET_BASE_URL")
            or os.environ.get("XCAGI_MARKET_BASE_URL")
            or os.environ.get("MODSTORE_PLATFORM_URL")
            or "http://127.0.0.1:8765"
        )
        .strip()
        .rstrip("/")
    )


def _strip_bearer(value: str) -> str:
    token = (value or "").strip()
    if token.lower().startswith("authorization:"):
        token = token.split(":", 1)[1].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _market_auth_token(user_id: str | None = None) -> str:
    token = _facade()._strip_bearer(
        os.environ.get("MODEL_USAGE_MARKET_AUTH_TOKEN")
        or os.environ.get("XCAGI_MARKET_AUTH_TOKEN")
        or os.environ.get("MODSTORE_AUTH_TOKEN")
        or ""
    )
    if token:
        return cast(str, token)
    try:
        from app.fastapi_routes.market_account import latest_session_market_token

        uid_int: int | None = None
        if user_id:
            try:
                uid_int = int(str(user_id).strip())
            except (TypeError, ValueError):
                uid_int = None
        return cast(str, _facade()._strip_bearer(latest_session_market_token(user_id=uid_int)))
    except (AttributeError, ImportError, OSError, RuntimeError):
        return ""


def _market_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("MODEL_USAGE_MARKET_TIMEOUT") or "10"))
    except ValueError:
        return 10.0


def _market_post_json(
    path: str, *, token: str, payload: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    base = _facade()._market_base_url()
    if not base:
        return (None, {"status": "market_debit_failed", "message": "market_base_url_missing"})
    if not token:
        return (None, {"status": "market_auth_missing", "message": "market_auth_token_missing"})
    url = f"{base}{path}"
    try:
        with _facade().httpx.Client(timeout=_facade()._market_timeout(), trust_env=False) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except _facade().httpx.HTTPError as exc:
        return (
            None,
            {
                "status": "market_debit_failed",
                "message": str(exc) or type(exc).__name__,
                "market_base_url": base,
                "path": path,
            },
        )
    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text[:500]}
    if response.status_code == 402:
        return (
            None,
            {
                "status": "insufficient_balance",
                "message": str(data.get("message") or data.get("detail") or "余额不足"),
                "market_base_url": base,
                "path": path,
            },
        )
    if response.status_code >= 400 or data.get("ok") is False or data.get("success") is False:
        msg = str(data.get("message") or data.get("detail") or data.get("error") or "")
        status = "insufficient_balance" if "余额不足" in msg else "market_debit_failed"
        return (
            None,
            {
                "status": status,
                "message": msg or f"HTTP {response.status_code}",
                "market_base_url": base,
                "path": path,
            },
        )
    return (data, None)


def _apply_market_wallet_debit(
    *, user_id: str, provider: str, model: str, cost_units: int, usage_key: str
) -> tuple[str, dict[str, Any]]:
    uid = _facade()._wallet_user_id(user_id)
    if cost_units <= 0:
        return ("unmetered", {"status": "not_required", "user_id": uid, "cost_units": 0})
    amount = _facade()._market_amount_for_cost_units(cost_units)
    token = _facade()._market_auth_token(user_id=user_id)
    request_id = (usage_key or f"usage_{uuid.uuid4().hex}")[:128]
    preauth_payload = {
        "amount": _facade()._money_str(amount),
        "provider": provider or "",
        "model": model or "",
        "request_id": request_id,
        "idempotency_key": f"{request_id}:preauth",
    }
    (preauth, err) = _facade()._market_post_json(
        "/api/wallet/ai/preauthorize", token=token, payload=preauth_payload
    )
    base_payload = {
        "backend": "market",
        "user_id": uid,
        "cost_units": cost_units,
        "amount_yuan": _facade()._money_str(amount),
        "market_base_url": _facade()._market_base_url(),
    }
    if err:
        return (str(err.get("status") or "market_debit_failed"), {**base_payload, **err})
    hold = preauth.get("hold") if isinstance(preauth, dict) else {}
    hold_no = str((hold or {}).get("hold_no") or "")
    if not hold_no:
        return (
            "market_debit_failed",
            {
                **base_payload,
                "status": "market_debit_failed",
                "message": "market_preauthorize_missing_hold_no",
                "preauthorize": preauth,
            },
        )
    settle_payload = {
        "hold_no": hold_no,
        "actual_amount": _facade()._money_str(amount),
        "idempotency_key": f"{request_id}:settle",
    }
    (settled, settle_err) = _facade()._market_post_json(
        "/api/wallet/ai/settle", token=token, payload=settle_payload
    )
    if settle_err:
        return (
            str(settle_err.get("status") or "market_debit_failed"),
            {
                **base_payload,
                **settle_err,
                "hold_no": hold_no,
                "preauthorized": True,
                "preauthorize": preauth,
            },
        )
    balance = settled.get("balance") if isinstance(settled, dict) else None
    return (
        "debited",
        {
            **base_payload,
            "status": "debited",
            "hold_no": hold_no,
            "balance_after_yuan": None if balance is None else _facade()._money_str(balance),
            "preauthorize": preauth,
            "settle": settled,
        },
    )


def _apply_market_wallet_refund(
    *, user_id: str, hold_no: str, amount_yuan: Any, refund_key: str, reason: str
) -> tuple[str, dict[str, Any]]:
    uid = _facade()._wallet_user_id(user_id)
    amount = _facade()._money(amount_yuan)
    if not hold_no:
        return (
            "refund_pending",
            {
                "status": "refund_pending",
                "user_id": uid,
                "message": "market_wallet_hold_no_missing",
            },
        )
    if amount <= 0:
        return ("not_required", {"status": "not_required", "user_id": uid, "amount_yuan": "0.00"})
    payload = {
        "hold_no": hold_no,
        "refund_amount": _facade()._money_str(amount),
        "reason": str(reason or "")[:128],
        "idempotency_key": str(refund_key or f"{hold_no}:refund")[:128],
    }
    (data, err) = _facade()._market_post_json(
        "/api/wallet/ai/refund",
        token=_facade()._market_auth_token(user_id=user_id),
        payload=payload,
    )
    base_payload = {
        "backend": "market",
        "user_id": uid,
        "hold_no": hold_no,
        "amount_yuan": _facade()._money_str(amount),
        "market_base_url": _facade()._market_base_url(),
    }
    if err:
        return ("refund_pending", {**base_payload, **err, "status": "refund_pending"})
    refund = data.get("refund") if isinstance(data, dict) else {}
    return (
        "refunded",
        {
            **base_payload,
            "status": "refunded",
            "balance_after_yuan": data.get("balance") if isinstance(data, dict) else None,
            "refund": refund if isinstance(refund, dict) else {},
        },
    )
