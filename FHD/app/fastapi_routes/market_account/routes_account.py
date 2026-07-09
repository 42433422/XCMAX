"""Market account overview routes."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.market_account._patch as _p
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter()

def _degraded_account_overview(message: str) -> dict[str, Any]:
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
        "market_base_url": _p._market_base_url(),
    }
def _merge_live_overview_fields(data: dict[str, Any], live: dict[str, Any]) -> None:
    for key in ("wallet", "plan", "membership", "quotas"):
        if live.get(key) is not None:
            data[key] = live.get(key)
    if isinstance(live.get("llm"), dict):
        current_llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
        data["llm"] = {**current_llm, **live["llm"]}
    if live.get("user") is not None:
        data["user"] = live.get("user")
def _bootstrap_overview_needs_live_merge(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return True
    return not (
        isinstance(data.get("user"), dict)
        and isinstance(data.get("wallet"), dict)
        and (isinstance(data.get("membership"), dict) or isinstance(data.get("plan"), dict))
    )
async def _market_llm_catalog_impl(request: Request, body: dict[str, Any]):
    authorization = await _p._authorization_from_request_resolved(request, body)
    if not authorization:
        return JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    refresh = "1" if bool(body.get("refresh")) else "0"
    payload = await _p._proxy_json(
        "GET",
        f"/api/llm/catalog?refresh={refresh}",
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw_error = payload.get("payload")
        msg = _p._error_message(raw_error, status_code)
        return {
            "success": True,
            "data": {
                "degraded": True,
                "providers": [],
                "sync_warning": msg,
                "market_base_url": _p._market_base_url(),
            },
        }
    if not isinstance(payload, dict):
        return {
            "success": True,
            "data": {
                "degraded": True,
                "providers": [],
                "sync_warning": "模型目录返回格式异常",
                "market_base_url": _p._market_base_url(),
            },
        }
    return {"success": True, "data": {**payload, "market_base_url": _p._market_base_url()}}
async def _legacy_account_overview(authorization: str) -> dict[str, Any]:
    """Compose account overview from older market APIs when /api/account/bootstrap is not deployed."""
    me = await _p._proxy_json(
        "GET", "/api/auth/me", authorization=authorization, return_error_payload=True
    )
    if isinstance(me, dict) and me.get("__proxy_error__"):
        return me
    wallet = await _p._proxy_json(
        "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
    )
    if isinstance(wallet, dict) and wallet.get("__proxy_error__"):
        balance = await _p._proxy_json(
            "GET", "/api/wallet/balance", authorization=authorization, return_error_payload=True
        )
        wallet_data = (
            {}
            if isinstance(balance, dict) and balance.get("__proxy_error__")
            else {"wallet": balance}
        )
    else:
        wallet_data = wallet if isinstance(wallet, dict) else {}
    plan = await _p._proxy_json(
        "GET", "/api/payment/my-plan", authorization=authorization, return_error_payload=True
    )
    plan_data = (
        {}
        if isinstance(plan, dict) and plan.get("__proxy_error__")
        else (plan if isinstance(plan, dict) else {})
    )
    llm = await _p._proxy_json(
        "GET", "/api/llm/status", authorization=authorization, return_error_payload=True
    )
    llm_data = (
        {}
        if isinstance(llm, dict) and llm.get("__proxy_error__")
        else (llm if isinstance(llm, dict) else {})
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
                [p for p in (llm_data.get("providers") or []) if p.get("has_user_override")]
            ),
        },
    }
@router.post("/account-sync")
async def market_account_sync(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    authorization = _p._auth_header(str(body.get("authorization") or body.get("token") or ""))
    if not authorization:
        hdr = str(
            request.headers.get("Authorization") or request.headers.get("authorization") or ""
        ).strip()
        if hdr:
            authorization = _p._auth_header(hdr)
    if not authorization:
        return JSONResponse({"success": False, "message": "authorization 必填"}, status_code=400)
    payload = await _p._proxy_json("GET", "/api/auth/me", authorization=authorization)
    if isinstance(payload, JSONResponse):
        return payload
    _p.save_session_market_token(
        _p.session_id_from_request(request), _p._normalize_bearer_token(authorization)
    )
    data = (
        payload.get("data")
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
        else payload
    )
    user = (
        data.get("user") if isinstance(data, dict) and isinstance(data.get("user"), dict) else data
    )
    return {"success": True, "data": {"user": user, "market_base_url": _p._market_base_url()}}

@router.post("/account-overview")
async def market_account_overview(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    try:
        authorization = await _p._authorization_from_request_resolved(request, body)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("market_account_overview: resolve authorization failed")
        return {
            "success": True,
            "data": _p._degraded_account_overview(f"读取市场令牌失败：{exc}"),
        }
    if not authorization:
        return JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    cache_key = _p._overview_cache_key(authorization)
    if not bool(body.get("refresh")):
        cached = _p._ACCOUNT_OVERVIEW_CACHE.get(cache_key)
        if cached is not None:
            stored_at, cached_data = cached
            if time.monotonic() - stored_at <= _p._account_overview_cache_ttl():
                data = dict(cached_data)
                data.setdefault("market_base_url", _p._market_base_url())
                return {"success": True, "data": data}
            _p._ACCOUNT_OVERVIEW_CACHE.pop(cache_key, None)
    try:
        payload = await _p._proxy_json(
            "GET", "/api/account/bootstrap", authorization=authorization, return_error_payload=True
        )
        data: dict[str, Any] | None = None
        sync_warning = ""

        if isinstance(payload, JSONResponse):
            try:
                import json as _json

                proxy_body = _json.loads(payload.body.decode() if payload.body else "{}")
                err = str(proxy_body.get("message") or proxy_body.get("detail") or "市场服务不可用")
            except RECOVERABLE_ERRORS:
                err = "市场服务不可用"
            data = _p._degraded_account_overview(err)
            sync_warning = err
        elif isinstance(payload, dict) and not payload.get("__proxy_error__"):
            raw = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            data = raw if isinstance(raw, dict) else None
            if isinstance(data, dict):
                if _p._bootstrap_overview_needs_live_merge(data):
                    live = await _p._legacy_account_overview(authorization)
                    if isinstance(live, dict) and not live.get("__proxy_error__"):
                        _p._merge_live_overview_fields(data, live)
                    elif isinstance(live, dict) and live.get("__proxy_error__"):
                        sync_warning = _p._error_message(
                            live.get("payload"), int(live.get("status_code") or 502)
                        )

        if data is None:
            legacy = await _p._legacy_account_overview(authorization)
            if isinstance(legacy, dict) and not legacy.get("__proxy_error__"):
                data = legacy
            else:
                err = ""
                if isinstance(legacy, dict) and legacy.get("__proxy_error__"):
                    err = _p._error_message(
                        legacy.get("payload"), int(legacy.get("status_code") or 502)
                    )
                elif isinstance(payload, dict) and payload.get("__proxy_error__"):
                    err = _p._error_message(
                        payload.get("payload"), int(payload.get("status_code") or 502)
                    )
                else:
                    err = "无法连接修茈市场服务器"
                data = _p._degraded_account_overview(err)
                logger.warning(
                    "market_account_overview degraded: %s (base=%s)", err, _p._market_base_url()
                )

        if not isinstance(data, dict):
            data = _p._degraded_account_overview("市场账户概览返回格式异常")

        data = {**data, "market_base_url": _p._market_base_url()}
        if sync_warning and not data.get("sync_warning"):
            data["sync_warning"] = sync_warning
        _p._ACCOUNT_OVERVIEW_CACHE[cache_key] = (time.monotonic(), dict(data))
        return {"success": True, "data": data}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("market_account_overview failed")
        return {
            "success": True,
            "data": _p._degraded_account_overview(f"账户概览异常：{exc}"),
        }

@router.post("/llm-catalog")
async def market_llm_catalog_post(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    return await _p._market_llm_catalog_impl(request, body)

@router.get("/llm-catalog")
async def market_llm_catalog_get(request: Request, refresh: bool = False):
    return await _p._market_llm_catalog_impl(request, {"refresh": refresh})
