"""管理端钱包在 Java 支付模式下读写 Java 账本。

模型预授权走 ``/api/wallet``，生产上由 Java 入账。管理端路径在 ``/api/admin``，
支付代理不会转发，所以这里按内部密钥把加款和列表直接交给 Java。
"""

from __future__ import annotations

import importlib
import os
import uuid
from decimal import Decimal
from typing import Any

import httpx


def payment_backend_is_java() -> bool:
    return os.environ.get("PAYMENT_BACKEND", "").strip().lower() == "java"


def credit_user(user_id: int, amount: Decimal, description: str) -> dict[str, Any]:
    payload = _call(
        "POST",
        "/api/internal/payment/wallet/credit",
        json_body={
            "user_id": int(user_id),
            "amount": format(amount, ".2f"),
            "description": description,
            "idempotency_key": f"admin_credit:{int(user_id)}:{uuid.uuid4().hex}",
        },
    )
    if payload.get("source") != "java_postgresql" or "balance" not in payload:
        raise _http_error(503, "Java 钱包服务回执无效")
    return payload


def list_wallets(limit: int, offset: int) -> dict[str, Any]:
    payload = _call(
        "GET",
        "/api/internal/payment/wallets",
        params={"limit": int(limit), "offset": int(offset)},
    )
    if payload.get("source") != "java_postgresql" or not isinstance(payload.get("items"), list):
        raise _http_error(503, "Java 钱包服务回执无效")
    return payload


def list_transactions(limit: int, offset: int) -> dict[str, Any]:
    payload = _call(
        "GET",
        "/api/internal/payment/transactions",
        params={"limit": int(limit), "offset": int(offset)},
    )
    if payload.get("source") != "java_postgresql" or not isinstance(payload.get("items"), list):
        raise _http_error(503, "Java 钱包服务回执无效")
    return payload


def _call(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, int] | None = None,
) -> dict[str, Any]:
    key = (
        os.environ.get("MODSTORE_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or ""
    ).strip()
    if not key:
        raise _http_error(503, "Java 钱包服务密钥未配置")
    base = (os.environ.get("JAVA_PAYMENT_SERVICE_URL") or "http://127.0.0.1:8080").rstrip("/")
    try:
        response = httpx.request(
            method,
            f"{base}{path}",
            headers={"X-Internal-Api-Key": key},
            json=json_body,
            params=params,
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise _http_error(503, "Java 钱包服务不可用") from exc
    if response.status_code == 404:
        raise _http_error(404, "用户不存在")
    if response.status_code == 400:
        raise _http_error(400, _error_message(response) or "加款金额无效")
    if response.status_code >= 400:
        raise _http_error(503, "Java 钱包服务调用失败")
    try:
        payload = response.json()
    except ValueError as exc:
        raise _http_error(503, "Java 钱包服务回执无效") from exc
    if not isinstance(payload, dict) or payload.get("ok") is False:
        raise _http_error(503, "Java 钱包服务回执无效")
    return payload


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        message = body.get("message") or body.get("detail") or ""
        return str(message).strip()
    return ""


def _http_error(status_code: int, message: str):
    facade = importlib.import_module("modstore_server.api.market_routes")
    return facade.HTTPException(status_code, message)
