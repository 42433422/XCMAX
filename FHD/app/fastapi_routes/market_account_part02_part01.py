# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


async def _proxy_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, _facade().Any] | None = None,
    authorization: str = "",
    extra_headers: dict[str, str] | None = None,
    return_error_payload: bool = False,
    sensitive: bool = False,
    timeout: float | None = None,
    retries: int | None = None,
):
    url = f"{_facade()._market_base_url()}{path}"
    headers: dict[str, str] = {"Accept": "application/json"}
    if authorization:
        headers["Authorization"] = _facade()._auth_header(authorization)
    if extra_headers:
        for key, val in extra_headers.items():
            if key and val:
                headers[str(key)] = str(val)
    timeout = _facade()._market_http_timeout() if timeout is None else float(timeout)
    retries = _facade()._market_http_retries() if retries is None else max(0, int(retries))
    last_exc: Exception | None = None
    mutating = str(method).upper() in {"POST", "PUT", "PATCH", "DELETE"}
    for attempt in range(retries):
        try:
            async with _facade().httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                req_headers = dict(headers)
                if mutating:
                    try:
                        await client.get(f"{_facade()._market_base_url()}/api/csrf")
                        csrf = client.cookies.get("csrf_token")
                        if csrf:
                            req_headers["X-CSRF-Token"] = csrf
                    except _facade().httpx.HTTPError:
                        pass
                res = await client.request(method, url, json=json_body, headers=req_headers)
            break
        except _facade().httpx.HTTPError as exc:
            last_exc = exc
            if attempt + 1 >= retries:
                message, status_code = _facade()._transport_error_message(exc)
                return _facade().JSONResponse(
                    {
                        "success": False,
                        "message": message,
                        "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                        "data": {"market_base_url": _facade()._market_base_url()},
                    },
                    status_code=status_code,
                )
        except _facade().RECOVERABLE_ERRORS as exc:
            if sensitive:
                _facade().logger.warning("market authentication transport unavailable")
            else:
                _facade().logger.warning("_proxy_json transport error to %s: %s", url, exc)
            message, status_code = _facade()._transport_error_message(exc)
            return _facade().JSONResponse(
                {
                    "success": False,
                    "message": message,
                    "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                    "data": {"market_base_url": _facade()._market_base_url()},
                },
                status_code=status_code,
            )
    else:
        if last_exc is not None:
            message, status_code = _facade()._transport_error_message(last_exc)
            return _facade().JSONResponse(
                {
                    "success": False,
                    "message": message,
                    "error": {"code": "MARKET_AUTH_UNAVAILABLE", "message": message},
                    "data": {"market_base_url": _facade()._market_base_url()},
                },
                status_code=status_code,
            )
        return _facade().JSONResponse(
            {"success": False, "message": "市场请求失败"}, status_code=502
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"detail": res.text}
    if res.status_code >= 400:
        if res.status_code >= 500 and sensitive:
            _facade().logger.warning(
                "market authentication request failed status=%s", res.status_code
            )
        elif res.status_code >= 500:
            _facade().logger.warning(
                "market proxy %s %s -> %s body=%s",
                method,
                url,
                res.status_code,
                _facade()._body_snippet(payload),
            )
        if return_error_payload:
            return {"__proxy_error__": True, "status_code": res.status_code, "payload": payload}
        detail = _facade()._error_message(payload, res.status_code)
        return _facade().JSONResponse(
            {
                "success": False,
                "message": str(detail),
                "data": {
                    **(payload if isinstance(payload, dict) else {}),
                    "market_base_url": _facade()._market_base_url(),
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
        data = await _facade()._proxy_json(
            "GET", "/api/payment/my-plan", authorization=token, return_error_payload=True
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("fetch_market_membership_tier 调用失败", exc_info=True)
        return None
    if not isinstance(data, dict) or data.get("__proxy_error__"):
        return None
    membership = data.get("membership")
    if isinstance(membership, dict):
        tier = str(membership.get("tier") or "").strip()
        return tier or None
    return None


@_facade().router.get("/membership-plans")
async def market_membership_plans():
    """会员套餐列表（代理市场公开接口 ``GET /api/payment/plans``）。

    供 ModelPaymentView 读取，替代前端硬编码；市场不可达时返回空列表，前端用本地 FALLBACK。
    """
    data = await _facade()._proxy_json("GET", "/api/payment/plans", return_error_payload=True)
    if isinstance(data, dict) and (not data.get("__proxy_error__")):
        plans = data.get("plans")
        return {"success": True, "data": {"plans": plans if isinstance(plans, list) else []}}
    return {"success": True, "data": {"plans": []}}


def _token_from_auth_response(payload: _facade().Any) -> str:
    """Extract access JWT from market ``POST /api/auth/login`` JSON (several response shapes)."""
    if not isinstance(payload, dict):
        return ""
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else None
    candidates: list[_facade().Any] = []
    if inner:
        candidates.extend(
            [inner.get("access_token"), inner.get("token"), inner.get("market_access_token")]
        )
        nested = inner.get("tokens") if isinstance(inner.get("tokens"), dict) else None
        if nested:
            candidates.extend([nested.get("access_token"), nested.get("accessToken")])
    candidates.extend(
        [payload.get("access_token"), payload.get("token"), payload.get("market_access_token")]
    )
    nested_top = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else None
    if nested_top:
        candidates.extend([nested_top.get("access_token"), nested_top.get("accessToken")])
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""


def _refresh_token_from_auth_response(payload: _facade().Any) -> str:
    if not isinstance(payload, dict):
        return ""
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else None
    candidates: list[_facade().Any] = []
    if inner:
        candidates.extend([inner.get("refresh_token"), inner.get("refreshToken")])
        nested = inner.get("tokens") if isinstance(inner.get("tokens"), dict) else None
        if nested:
            candidates.extend([nested.get("refresh_token"), nested.get("refreshToken")])
    candidates.extend([payload.get("refresh_token"), payload.get("refreshToken")])
    nested_top = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else None
    if nested_top:
        candidates.extend([nested_top.get("refresh_token"), nested_top.get("refreshToken")])
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""


async def refresh_session_market_token(session_id: str) -> str:
    """Use persisted modstore refresh_token to obtain a new access_token."""
    sid = (session_id or "").strip()
    if not sid:
        return ""
    refresh = _facade().session_market_refresh_token(sid)
    if not refresh:
        return ""
    payload = await _facade()._proxy_json(
        "POST", "/api/auth/refresh", json_body={"refresh_token": refresh}, return_error_payload=True
    )
    if isinstance(payload, _facade().JSONResponse):
        return ""
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return ""
    access = _facade()._token_from_auth_response(payload)
    new_refresh = _facade()._refresh_token_from_auth_response(payload) or refresh
    if access and sid:
        _facade().save_session_market_token(sid, access, new_refresh)
    return access


async def resolve_valid_market_access_token(session_id: str) -> str:
    """Return a working market access token, refreshing when /api/auth/me returns 401."""
    from app.application.surface_audit_demo_account import is_local_demo_market_token

    sid = (session_id or "").strip()
    user_id = _facade()._user_id_from_session(sid)
    tok = _facade()._normalize_bearer_token(_facade().session_market_token(sid))
    if not tok and user_id is not None:
        tok = _facade()._normalize_bearer_token(
            _facade().latest_session_market_token(user_id=user_id)
        )
    if not tok:
        return ""
    if is_local_demo_market_token(tok):
        return tok
    me = await _facade()._proxy_json(
        "GET", "/api/auth/me", authorization=f"Bearer {tok}", return_error_payload=True
    )
    if isinstance(me, _facade().JSONResponse):
        _facade().logger.warning(
            "market unreachable during token validation (session_id=%s), using local token",
            sid[:8] if sid else "",
        )
        return tok
    if isinstance(me, dict) and me.get("__proxy_error__"):
        if _facade()._proxy_error_http_status(me) == 401:
            refreshed = await _facade().refresh_session_market_token(sid)
            return _facade()._normalize_bearer_token(refreshed)
        _facade().logger.warning(
            "market /api/auth/me error status=%s, using local token", me.get("status_code")
        )
        return tok
    if isinstance(me, dict) and (me.get("ok") is False or me.get("success") is False):
        refreshed = await _facade().refresh_session_market_token(sid)
        return _facade()._normalize_bearer_token(refreshed)
    return tok


def _market_validate_fast_timeout() -> float:
    """会话校验专用快速超时：宁可 fail-open 也不阻塞导航。"""
    try:
        return max(0.5, float(_facade().os.environ.get("XCAGI_MARKET_VALIDATE_TIMEOUT", "2")))
    except ValueError:
        return 2.0


async def resolve_valid_market_access_token_fast(session_id: str) -> str:
    """返回市场 token，但绝不因市场慢而阻塞调用方。

    供路由守卫/会话校验等对延迟敏感的路径使用：用短超时 + 零重试探测
    /api/auth/me，任何瞬时失败（超时/连接不上/5xx）都直接返回本地 token
    （fail-open），因为本地会话本身已有效。仅当市场明确返回 401 判定
    token 过期时才尝试刷新。
    """
    from app.application.surface_audit_demo_account import is_local_demo_market_token

    sid = (session_id or "").strip()
    user_id = _facade()._user_id_from_session(sid)
    tok = _facade()._normalize_bearer_token(_facade().session_market_token(sid))
    if not tok and user_id is not None:
        tok = _facade()._normalize_bearer_token(
            _facade().latest_session_market_token(user_id=user_id)
        )
    if not tok:
        return ""
    if is_local_demo_market_token(tok):
        return tok
    try:
        me = await _facade()._proxy_json(
            "GET",
            "/api/auth/me",
            authorization=f"Bearer {tok}",
            return_error_payload=True,
            timeout=_facade()._market_validate_fast_timeout(),
            retries=0,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning(
            "market token fast-validate transport error (session_id=%s), fail-open to local token",
            sid[:8] if sid else "",
        )
        return tok
    if isinstance(me, _facade().JSONResponse):
        return tok
    if isinstance(me, dict) and me.get("__proxy_error__"):
        if _facade()._proxy_error_http_status(me) == 401:
            refreshed = await _facade().refresh_session_market_token(sid)
            return _facade()._normalize_bearer_token(refreshed)
        return tok
    if isinstance(me, dict) and (me.get("ok") is False or me.get("success") is False):
        refreshed = await _facade().refresh_session_market_token(sid)
        return _facade()._normalize_bearer_token(refreshed)
    return tok


def _looks_like_verification_required(payload: _facade().Any) -> bool:
    """Classify a market response without changing registration behavior."""
    msg = _facade()._error_message(payload, 400)
    return bool(_facade().re.search("验证码|verification|code", msg, _facade().re.I))


async def _register_without_verification(username: str, password: str, email: str):
    """Use the explicitly enabled server-side API for the dev diagnostic only.

    The public registration flow never calls this helper and therefore cannot
    silently bypass email verification.
    """
    payload = await _facade()._proxy_json(
        "POST",
        "/api/market/open/register",
        json_body={"username": username, "password": password, "email": email},
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        payload = await _facade()._proxy_json(
            "POST",
            "/api/auth/register-open",
            json_body={"username": username, "password": password, "email": email},
            return_error_payload=True,
        )
    return payload
