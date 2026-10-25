"""Authentication payload decoding and canonical identity/lifecycle projection."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .port_contracts import JsonObject, ProxyJSON


def _extract_auth_token(payload: Any, names: tuple[str, ...], nested_names: tuple[str, ...]) -> str:
    if not isinstance(payload, dict):
        return ""
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else None
    for layer in (inner, payload):
        if layer is None:
            continue
        candidates = [layer.get(name) for name in names]
        nested = layer.get("tokens") if isinstance(layer.get("tokens"), dict) else None
        if nested:
            candidates.extend(nested.get(name) for name in nested_names)
        for candidate in candidates:
            if candidate is not None:
                token = str(candidate).strip()
                if token:
                    return token
    return ""


def _token_from_auth_response(payload: Any) -> str:
    """Extract the first access token in the legacy payload precedence order."""
    return _extract_auth_token(
        payload, ("access_token", "token", "market_access_token"), ("access_token", "accessToken")
    )


def _refresh_token_from_auth_response(payload: Any) -> str:
    names = ("refresh_token", "refreshToken")
    return _extract_auth_token(payload, names, names)


def _is_local_market_base(url: str) -> bool:
    host = (url or "").strip().lower()
    return "127.0.0.1" in host or "localhost" in host


def _demo_market_login_payload(shim: dict[str, Any], *, market_base_url: str) -> dict[str, Any]:
    raw_out = dict(shim.get("raw") or {})
    if not isinstance(raw_out.get("user"), dict):
        raw_out["user"] = {
            "id": int((shim.get("raw") or {}).get("user", {}).get("id") or 900001),
            "username": str((shim.get("raw") or {}).get("user", {}).get("username") or ""),
            "is_enterprise": True,
            "is_admin": False,
        }
    return {
        "success": True,
        "market_base_url": market_base_url,
        "token": str(shim.get("token") or "").strip(),
        "refresh_token": str(shim.get("refresh_token") or "").strip(),
        "is_enterprise": bool(shim.get("is_enterprise")),
        "is_market_admin": bool(shim.get("is_market_admin")),
        "raw": raw_out,
    }


@dataclass
class AuthPayloads:
    proxy: ProxyJSON
    base_url: Callable[[], str]
    error_message: Callable[[Any, int], str]
    access_token: Callable[[Any], str]
    refresh_token: Callable[[Any], str]
    identity: Callable[[Any, Any], tuple[bool, bool, JsonObject]]
    lifecycle: Callable[[Any, Any], JsonObject]
    logger: Logger

    async def normalize(self, payload: Any, *, market_base: str | None = None) -> dict[str, Any]:
        """Turn market login JSON into normalized token payload."""
        if isinstance(payload, JSONResponse):
            try:
                raw_body = json.loads(bytes(payload.body).decode("utf-8") if payload.body else "{}")
            except RECOVERABLE_ERRORS:
                raw_body = {}
            status_code = int(payload.status_code or 502)
            message = (
                str(raw_body.get("message") or "").strip()
                or str(raw_body.get("detail") or "").strip()
                or self.error_message(raw_body, status_code)
            )
            err = raw_body.get("error") if isinstance(raw_body.get("error"), dict) else {}
            code = str(err.get("code") or "").strip()
            if status_code >= 500 and (not code):
                code = "MARKET_AUTH_UNAVAILABLE"
            return {
                "success": False,
                "message": message,
                "status_code": status_code,
                "error_code": code
                or ("MARKET_AUTH_UNAVAILABLE" if status_code >= 500 else "MARKET_AUTH_FAILED"),
                "raw": raw_body,
                "market_base_url": market_base or self.base_url(),
            }
        token = self.access_token(payload)
        refresh = self.refresh_token(payload)
        if not token:
            return {
                "success": False,
                "message": "市场登录成功但未返回 access_token",
                "raw": payload,
            }
        me = await self.proxy(
            "GET", "/api/auth/me", authorization=f"Bearer {token}", return_error_payload=True
        )
        is_enterprise, is_market_admin, user_blob = self.identity(payload, me)
        lifecycle = self.lifecycle(payload, me)
        self.logger.info(
            "market auth normalized base=%s success=True is_enterprise=%s is_market_admin=%s username=%s raw_keys=%s me_keys=%s",
            market_base or self.base_url(),
            is_enterprise,
            is_market_admin,
            str(user_blob.get("username") or ""),
            sorted(payload.keys()) if isinstance(payload, dict) else [],
            sorted(me.keys()) if isinstance(me, dict) else [],
        )
        raw_out = dict(payload) if isinstance(payload, dict) else {}
        if user_blob and (not isinstance(raw_out.get("user"), dict)):
            raw_out["user"] = user_blob
        return {
            "success": True,
            "market_base_url": market_base or self.base_url(),
            "token": token,
            "refresh_token": refresh,
            "is_enterprise": is_enterprise,
            "is_market_admin": is_market_admin,
            **lifecycle,
            "raw": raw_out,
        }
