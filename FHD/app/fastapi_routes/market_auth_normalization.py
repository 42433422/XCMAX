"""Normalize official market login payloads without coupling to route state."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse


async def normalize_market_auth_payload(
    payload: Any,
    *,
    market_base: str,
    timeout_seconds: float | None,
    proxy_json: Callable[..., Awaitable[Any]],
    token_from_response: Callable[[Any], str],
    refresh_token_from_response: Callable[[Any], str],
    identity_from_payloads: Callable[[Any, Any], tuple[bool, bool, dict[str, Any]]],
    error_message: Callable[[Any, int], str],
    logger: Any,
) -> dict[str, Any]:
    """Turn a password/phone-login response into the local session shape."""
    if isinstance(payload, JSONResponse):
        try:
            raw_body = json.loads(payload.body.decode("utf-8") if payload.body else "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            raw_body = {}
        status_code = int(payload.status_code or 502)
        message = (
            str(raw_body.get("message") or "").strip()
            or str(raw_body.get("detail") or "").strip()
            or error_message(raw_body, status_code)
        )
        err = raw_body.get("error") if isinstance(raw_body.get("error"), dict) else {}
        code = str(err.get("code") or "").strip()
        if status_code >= 500 and not code:
            code = "MARKET_AUTH_UNAVAILABLE"
        return {
            "success": False,
            "message": message,
            "status_code": status_code,
            "error_code": code
            or ("MARKET_AUTH_UNAVAILABLE" if status_code >= 500 else "MARKET_AUTH_FAILED"),
            "raw": raw_body,
            "market_base_url": market_base,
        }
    token = token_from_response(payload)
    refresh = refresh_token_from_response(payload)
    if not token:
        return {"success": False, "message": "市场登录成功但未返回 access_token", "raw": payload}
    login_is_enterprise, login_is_market_admin, login_user_blob = identity_from_payloads(payload, {})
    identity_is_sufficient = bool(login_user_blob) and (
        login_is_enterprise or login_is_market_admin
    )
    profile: Any = {}
    if not identity_is_sufficient:
        profile = await proxy_json(
            "GET",
            "/api/auth/me",
            authorization=f"Bearer {token}",
            return_error_payload=True,
            timeout_seconds=timeout_seconds,
        )
    is_enterprise, is_market_admin, user_blob = identity_from_payloads(payload, profile)
    logger.info(
        "market auth normalized base=%s success=True is_enterprise=%s is_market_admin=%s username=%s raw_keys=%s me_keys=%s profile_refresh_skipped=%s",
        market_base,
        is_enterprise,
        is_market_admin,
        str(user_blob.get("username") or ""),
        sorted(payload.keys()) if isinstance(payload, dict) else [],
        sorted(profile.keys()) if isinstance(profile, dict) else [],
        identity_is_sufficient,
    )
    raw_out = dict(payload) if isinstance(payload, dict) else {}
    if user_blob and not isinstance(raw_out.get("user"), dict):
        raw_out["user"] = user_blob
    return {
        "success": True,
        "market_base_url": market_base,
        "token": token,
        "refresh_token": refresh,
        "is_enterprise": is_enterprise,
        "is_market_admin": is_market_admin,
        "raw": raw_out,
    }
