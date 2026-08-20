# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


@_facade().router.post("/login-with-phone-code")
async def market_login_with_phone_code_route(
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    phone = str(body.get("phone") or "").strip()
    code = str(body.get("code") or "").strip()
    if not phone or not code:
        return _facade().JSONResponse(
            {"success": False, "message": "请填写手机号和验证码"}, status_code=400
        )
    result = await _facade().login_market_with_phone_code(phone, code)
    if not result.get("success"):
        status = int(result.get("status_code") or 401)
        return _facade().JSONResponse(
            {
                "success": False,
                "message": result.get("message"),
                "error": {
                    "code": result.get("error_code") or "MARKET_AUTH_FAILED",
                    "message": result.get("message"),
                },
            },
            status_code=status if status >= 400 else 401,
        )
    return {
        "success": True,
        "data": {
            "token": result.get("token"),
            "refresh_token": result.get("refresh_token"),
            "market_base_url": result.get("market_base_url"),
        },
    }


@_facade().router.post("/account-sync")
async def market_account_sync(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    authorization = _facade()._auth_header(
        str(body.get("authorization") or body.get("token") or "")
    )
    if not authorization:
        hdr = str(
            request.headers.get("Authorization") or request.headers.get("authorization") or ""
        ).strip()
        if hdr:
            authorization = _facade()._auth_header(hdr)
    if not authorization:
        return _facade().JSONResponse(
            {"success": False, "message": "authorization 必填"}, status_code=400
        )
    payload = await _facade()._proxy_json("GET", "/api/auth/me", authorization=authorization)
    if isinstance(payload, _facade().JSONResponse):
        return payload
    _facade().save_session_market_token(
        _facade().session_id_from_request(request), _facade()._normalize_bearer_token(authorization)
    )
    data = (
        payload.get("data")
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
        else payload
    )
    user = (
        data.get("user") if isinstance(data, dict) and isinstance(data.get("user"), dict) else data
    )
    return {
        "success": True,
        "data": {"user": user, "market_base_url": _facade()._market_base_url()},
    }


def _degraded_account_overview(message: str) -> dict[str, _facade().Any]:
    """Market unreachable — return 200 so SPA can still show wallet/plan links."""
    return {
        "degraded": True,
        "market_unreachable": True,
        "sync_warning": message,
        "user": {},
        "wallet": {"balance": None},
        "membership": {"label": "未同步", "tier": "unknown", "can_byok": False},
        "quotas": [],
        "llm": {"providers": []},
        "market_base_url": _facade()._market_base_url(),
    }


def _merge_live_overview_fields(
    data: dict[str, _facade().Any], live: dict[str, _facade().Any]
) -> None:
    for key in ("wallet", "plan", "membership", "quotas"):
        if live.get(key) is not None:
            data[key] = live.get(key)
    if isinstance(live.get("llm"), dict):
        raw_current_llm = data.get("llm")
        current_llm: dict[str, _facade().Any] = (
            dict(raw_current_llm) if isinstance(raw_current_llm, dict) else {}
        )
        data["llm"] = {**current_llm, **dict(live["llm"])}
    if live.get("user") is not None:
        data["user"] = live.get("user")


@_facade().router.post("/account-overview")
async def market_account_overview(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    try:
        authorization = await _facade()._authorization_from_request_resolved(request, body)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("market_account_overview: resolve authorization failed")
        return {
            "success": True,
            "data": _facade()._degraded_account_overview(f"读取市场令牌失败：{exc}"),
        }
    if not authorization:
        return _facade().JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    cache_key = _facade()._overview_cache_key(authorization)
    if not bool(body.get("refresh")):
        cached = _facade()._ACCOUNT_OVERVIEW_CACHE.get(cache_key)
        if cached is not None:
            stored_at, cached_data = cached
            if _facade().time.monotonic() - stored_at <= _facade()._account_overview_cache_ttl():
                cached_overview = dict(cached_data)
                cached_overview.setdefault("market_base_url", _facade()._market_base_url())
                return {"success": True, "data": cached_overview}
            _facade()._ACCOUNT_OVERVIEW_CACHE.pop(cache_key, None)
    try:
        payload = await _facade()._proxy_json(
            "GET", "/api/account/bootstrap", authorization=authorization, return_error_payload=True
        )
        data: dict[str, _facade().Any] | None = None
        sync_warning = ""
        if isinstance(payload, _facade().JSONResponse):
            try:
                import json as _json

                proxy_body = _json.loads(bytes(payload.body).decode() if payload.body else "{}")
                err = str(proxy_body.get("message") or proxy_body.get("detail") or "市场服务不可用")
            except _facade().RECOVERABLE_ERRORS:
                err = "市场服务不可用"
            data = _facade()._degraded_account_overview(err)
            sync_warning = err
        elif isinstance(payload, dict) and (not payload.get("__proxy_error__")):
            raw = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            data = dict(raw) if isinstance(raw, dict) else None
            if isinstance(data, dict):
                if _facade()._market_account_live.bootstrap_overview_needs_live_merge(data):
                    live = await _facade()._legacy_account_overview(authorization)
                    if isinstance(live, dict) and (not live.get("__proxy_error__")):
                        _facade()._merge_live_overview_fields(data, live)
                    elif isinstance(live, dict) and live.get("__proxy_error__"):
                        sync_warning = _facade()._error_message(
                            live.get("payload"), int(live.get("status_code") or 502)
                        )
        if data is None:
            legacy = await _facade()._legacy_account_overview(authorization)
            if isinstance(legacy, dict) and (not legacy.get("__proxy_error__")):
                data = legacy
            else:
                err = ""
                if isinstance(legacy, dict) and legacy.get("__proxy_error__"):
                    err = _facade()._error_message(
                        legacy.get("payload"), int(legacy.get("status_code") or 502)
                    )
                elif isinstance(payload, dict) and payload.get("__proxy_error__"):
                    err = _facade()._error_message(
                        payload.get("payload"), int(payload.get("status_code") or 502)
                    )
                else:
                    err = "无法连接修茈市场服务器"
                data = _facade()._degraded_account_overview(err)
                _facade().logger.warning(
                    "market_account_overview degraded: %s (base=%s)",
                    err,
                    _facade()._market_base_url(),
                )
        if not isinstance(data, dict):
            data = _facade()._degraded_account_overview("市场账户概览返回格式异常")
        sync_warning = await _facade()._market_account_live.refresh_overview_wallet(
            data,
            authorization,
            sync_warning,
            proxy_json=_facade()._proxy_json,
            error_message=_facade()._error_message,
        )
        data = {**data, "market_base_url": _facade()._market_base_url()}
        if sync_warning and (not data.get("sync_warning")):
            data["sync_warning"] = sync_warning
        _facade()._ACCOUNT_OVERVIEW_CACHE[cache_key] = (_facade().time.monotonic(), dict(data))
        return {"success": True, "data": data}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("market_account_overview failed")
        return {
            "success": True,
            "data": _facade()._degraded_account_overview(f"账户概览异常：{exc}"),
        }


async def _market_llm_catalog_impl(request: _facade().Request, body: dict[str, _facade().Any]):
    authorization = await _facade()._authorization_from_request_resolved(request, body)
    if not authorization:
        return _facade().JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    refresh = "1" if bool(body.get("refresh")) else "0"
    payload = await _facade()._proxy_json(
        "GET",
        f"/api/llm/catalog?refresh={refresh}",
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(payload, _facade().JSONResponse):
        return _facade()._market_account_live.degraded_llm_catalog(
            payload, _facade()._market_base_url()
        )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw_error = payload.get("payload")
        msg = _facade()._error_message(raw_error, status_code)
        return {
            "success": True,
            "data": {
                "degraded": True,
                "providers": [],
                "sync_warning": msg,
                "market_base_url": _facade()._market_base_url(),
            },
        }
    if not isinstance(payload, dict):
        return {
            "success": True,
            "data": {
                "degraded": True,
                "providers": [],
                "sync_warning": "模型目录返回格式异常",
                "market_base_url": _facade()._market_base_url(),
            },
        }
    return {"success": True, "data": {**payload, "market_base_url": _facade()._market_base_url()}}


@_facade().router.post("/llm-catalog")
async def market_llm_catalog_post(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    return await _facade()._market_llm_catalog_impl(request, body)


@_facade().router.get("/llm-catalog")
async def market_llm_catalog_get(request: _facade().Request, refresh: bool = False):
    return await _facade()._market_llm_catalog_impl(request, {"refresh": refresh})


async def _legacy_account_overview(authorization: str) -> dict[str, _facade().Any]:
    """Compose account overview from older market APIs when /api/account/bootstrap is not deployed."""
    me = await _facade()._proxy_json(
        "GET", "/api/auth/me", authorization=authorization, return_error_payload=True
    )
    if isinstance(me, dict) and me.get("__proxy_error__"):
        return me
    wallet = await _facade()._proxy_json(
        "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
    )
    if isinstance(wallet, dict) and wallet.get("__proxy_error__"):
        balance = await _facade()._proxy_json(
            "GET", "/api/wallet/balance", authorization=authorization, return_error_payload=True
        )
        wallet_data = (
            {}
            if isinstance(balance, dict) and balance.get("__proxy_error__")
            else {"wallet": balance}
        )
    else:
        wallet_data = wallet if isinstance(wallet, dict) else {}
    plan = await _facade()._proxy_json(
        "GET", "/api/payment/my-plan", authorization=authorization, return_error_payload=True
    )
    plan_data = (
        {}
        if isinstance(plan, dict) and plan.get("__proxy_error__")
        else plan
        if isinstance(plan, dict)
        else {}
    )
    llm = await _facade()._proxy_json(
        "GET", "/api/llm/status", authorization=authorization, return_error_payload=True
    )
    llm_data = (
        {}
        if isinstance(llm, dict) and llm.get("__proxy_error__")
        else llm
        if isinstance(llm, dict)
        else {}
    )
    user = me.get("user") if isinstance(me, dict) and isinstance(me.get("user"), dict) else me
    wallet_obj = (
        wallet_data.get("wallet") if isinstance(wallet_data.get("wallet"), dict) else wallet_data
    )
    return {
        "success": True,
        "user": user,
        "wallet": wallet_obj,
        "plan": plan_data.get("plan"),
        "membership": plan_data.get("membership"),
        "quotas": plan_data.get("quotas") or [],
        "llm": {
            "providers": llm_data.get("providers") or [],
            "fernet_configured": llm_data.get("fernet_configured"),
            "byok_configured_count": len(
                [p for p in llm_data.get("providers") or [] if p.get("has_user_override")]
            ),
        },
    }


def _market_auth_from_request(request: _facade().Request) -> str:
    sid = _facade().session_id_from_request(request)
    tok = _facade().session_market_token(sid)
    if tok:
        return tok
    return str(request.headers.get("Authorization") or "").strip()


@_facade().router.get("/payment/plans")
async def market_payment_plans(request: _facade().Request):
    """修茈市场套餐（含微信/支付宝统一收银，Java SoT）。"""
    payload = await _facade()._proxy_json(
        "GET",
        "/api/payment/plans",
        authorization=_facade()._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _facade()._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload, "market_base_url": _facade()._market_base_url()}
