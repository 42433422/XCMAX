"""HTTP proxy helpers for Xiuci market APIs."""

from __future__ import annotations

import logging
import os
import re
from hashlib import sha256
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.market_account._patch as _p
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_ACCOUNT_OVERVIEW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

def _market_base_url() -> str:
    return (os.environ.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:8765").strip().rstrip("/")
def _auth_header(raw: str) -> str:
    token = (raw or "").strip()
    if token.lower().startswith("authorization:"):
        token = token.split(":", 1)[1].strip()
    if token and not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return token
def _normalize_bearer_token(raw: str) -> str:
    """Strip ``Bearer `` prefix for consistent ``market_access_token`` JSON fields."""
    t = (raw or "").strip()
    if t.lower().startswith("bearer "):
        return t[7:].strip()
    return t
def _proxy_error_http_status(payload: Any) -> int | None:
    """Parse HTTP status from ``_proxy_json(..., return_error_payload=True)`` error dict."""
    if not isinstance(payload, dict) or not payload.get("__proxy_error__"):
        return None
    raw = payload.get("status_code")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
def _authorization_from_request(request: Request, body: dict[str, Any]) -> str:
    """Current desktop session token → newest persisted token → explicit browser token.

    The browser may keep an old market JWT in localStorage while the local backend already has
    a fresh token bound to the current FHD login session. Strong account state should follow the
    backend session, not stale client storage.
    """
    sid = _p.session_id_from_request(request)
    session_auth = _auth_header(_p.session_market_token(sid))
    if session_auth:
        return session_auth
    # 多用户环境按当前登录 user_id 过滤，防止串号
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        current_user = resolve_session_user(request)
        user_id = getattr(current_user, "id", None) if current_user else None
    except RECOVERABLE_ERRORS:
        user_id = None
    if sid or user_id is not None:
        latest_auth = _auth_header(_p.latest_session_market_token(user_id=user_id))
        if latest_auth:
            return latest_auth
    auth = _auth_header(str(body.get("authorization") or body.get("token") or ""))
    if auth:
        return auth
    hdr = str(
        request.headers.get("Authorization") or request.headers.get("authorization") or ""
    ).strip()
    if hdr:
        return _auth_header(hdr)
    return ""
async def _authorization_from_request_resolved(request: Request, body: dict[str, Any]) -> str:
    """Like ``_authorization_from_request`` but refreshes expired session-bound market JWTs."""
    sid = _p.session_id_from_request(request)
    # 多用户环境按当前登录 user_id 过滤，防止串号
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        current_user = resolve_session_user(request)
        user_id = getattr(current_user, "id", None) if current_user else None
    except RECOVERABLE_ERRORS:
        user_id = None
    session_tok = _normalize_bearer_token(_p.session_market_token(sid))
    if not session_tok and (sid or user_id is not None):
        session_tok = _normalize_bearer_token(_p.latest_session_market_token(user_id=user_id))
    if session_tok:
        resolved = await _p.resolve_valid_market_access_token(sid)
        if resolved:
            return _auth_header(resolved)
    return _p._authorization_from_request(request, body)
def _body_snippet(payload: Any, limit: int = 240) -> str:
    if isinstance(payload, dict):
        try:
            import json as _json

            text = _json.dumps(payload, ensure_ascii=False)
        except RECOVERABLE_ERRORS:
            text = str(payload)
    else:
        text = str(payload or "")
    text = text.replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")
def _error_message(payload: Any, status_code: int) -> str:
    base = _market_base_url()
    if status_code == 429:
        return "市场服务请求过于频繁，请稍后再试"
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, list):
            msg = "; ".join(str(x.get("msg") if isinstance(x, dict) else x) for x in detail)
        elif detail:
            msg = str(detail)
        else:
            msg = ""
        if status_code >= 500:
            hint = f"请检查 XCAGI_MARKET_BASE_URL={base}"
            if msg and not re.match(r"^internal server error$", msg, re.I):
                return f"市场服务返回 {status_code}：{msg}。{hint}"
            return f"市场服务返回 {status_code}（服务器内部错误）。{hint}"
        if msg:
            return msg
    if status_code >= 500:
        return f"市场服务返回 {status_code}（服务器内部错误）。请检查 XCAGI_MARKET_BASE_URL={base}"
    return f"HTTP {status_code}"
def _market_http_timeout() -> float:
    try:
        return float(os.environ.get("XCAGI_MARKET_HTTP_TIMEOUT", "20"))
    except ValueError:
        return 20.0
def _market_http_retries() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_MARKET_HTTP_RETRIES", "1")))
    except ValueError:
        return 1
def _account_overview_cache_ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("XCAGI_MARKET_OVERVIEW_CACHE_TTL", "45")))
    except ValueError:
        return 45.0
def _overview_cache_key(authorization: str) -> str:
    return sha256(_auth_header(authorization).encode("utf-8")).hexdigest()
def _transport_error_message(exc: Exception) -> tuple[str, int]:
    import httpx

    label = str(exc).strip() or type(exc).__name__
    base = _market_base_url()
    if isinstance(exc, httpx.ReadTimeout):
        return (
            f"连接修茈市场超时（{label}）。请检查网络或增大 XCAGI_MARKET_HTTP_TIMEOUT；"
            f"当前 XCAGI_MARKET_BASE_URL={base}",
            503,
        )
    return (
        f"无法连接修茈市场服务器：{label}。请确认 XCAGI_MARKET_BASE_URL={base} 可达，且 FHD 后端已启动。",
        502,
    )
async def _proxy_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    authorization: str = "",
    extra_headers: dict[str, str] | None = None,
    return_error_payload: bool = False,
):
    url = f"{_market_base_url()}{path}"
    headers: dict[str, str] = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = _auth_header(authorization)
    if extra_headers:
        for key, val in extra_headers.items():
            if key and val:
                headers[str(key)] = str(val)
    timeout = _market_http_timeout()
    retries = _market_http_retries()
    last_exc: Exception | None = None
    mutating = str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"}
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                req_headers = dict(headers)
                if mutating:
                    # 市场对变更类请求强制 CSRF 双提交:先 GET 任意端点拿 csrf_token cookie,
                    # 再以同值 X-CSRF-Token 头回传(cookie 由同一 client 自动携带)。
                    # 失败不阻断主请求(老市场无 CSRF 时无副作用)。
                    try:
                        await client.get(f"{_market_base_url()}/api/csrf")
                        csrf = client.cookies.get("csrf_token")
                        if csrf:
                            req_headers["X-CSRF-Token"] = csrf
                    except httpx.HTTPError:
                        pass
                res = await client.request(method, url, json=json_body, headers=req_headers)
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt + 1 >= retries:
                message, status_code = _transport_error_message(exc)
                return JSONResponse(
                    {
                        "success": False,
                        "message": message,
                        "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                        "data": {"market_base_url": _market_base_url()},
                    },
                    status_code=status_code,
                )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("_proxy_json transport error to %s: %s", url, exc)
            message, status_code = _transport_error_message(exc)
            return JSONResponse(
                {
                    "success": False,
                    "message": message,
                    "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                    "data": {"market_base_url": _market_base_url()},
                },
                status_code=status_code,
            )
    else:
        if last_exc is not None:
            message, status_code = _transport_error_message(last_exc)
            return JSONResponse(
                {
                    "success": False,
                    "message": message,
                    "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                    "data": {"market_base_url": _market_base_url()},
                },
                status_code=status_code,
            )
        return JSONResponse({"success": False, "message": "市场请求失败"}, status_code=502)
    try:
        payload = res.json()
    except ValueError:
        payload = {"detail": res.text}
    if res.status_code >= 400:
        if res.status_code >= 500:
            logger.warning(
                "market proxy %s %s -> %s body=%s",
                method,
                url,
                res.status_code,
                _body_snippet(payload),
            )
        if return_error_payload:
            return {"__proxy_error__": True, "status_code": res.status_code, "payload": payload}
        detail = _error_message(payload, res.status_code)
        return JSONResponse(
            {
                "success": False,
                "message": str(detail),
                "data": {
                    **(payload if isinstance(payload, dict) else {}),
                    "market_base_url": _market_base_url(),
                },
            },
            status_code=res.status_code,
        )
    return payload
async def fetch_market_membership_tier(market_token: str) -> str | None:
    """登录后从修茈市场拉取当前用户会员等级 tier（free/vip/vip_plus/svip1..8）。

    市场登录响应不含会员等级，需单独调 ``GET /api/payment/my-plan``。
    任何失败均返回 None（不阻断登录）。
    """
    token = (market_token or "").strip()
    if not token:
        return None
    try:
        data = await _p._proxy_json(
            "GET", "/api/payment/my-plan", authorization=token, return_error_payload=True
        )
    except RECOVERABLE_ERRORS:
        logger.warning("fetch_market_membership_tier 调用失败", exc_info=True)
        return None
    if not isinstance(data, dict) or data.get("__proxy_error__"):
        return None
    membership = data.get("membership")
    if isinstance(membership, dict):
        tier = str(membership.get("tier") or "").strip()
        return tier or None
    return None
