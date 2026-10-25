"""Account projections, credential-keyed cache and legacy/live read fallbacks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.market_bridge.protocols import (
    JsonObject,
    ProxyJSON,
    RefreshWallet,
    RequestAuthorization,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _merge_live_overview_fields(data: dict[str, Any], live: dict[str, Any]) -> None:
    for key in ("wallet", "plan", "membership", "quotas"):
        if live.get(key) is not None:
            data[key] = live.get(key)
    if isinstance(live.get("llm"), dict):
        raw_current_llm = data.get("llm")
        current_llm: dict[str, Any] = (
            dict(raw_current_llm) if isinstance(raw_current_llm, dict) else {}
        )
        data["llm"] = {**current_llm, **dict(live["llm"])}
    if live.get("user") is not None:
        data["user"] = live.get("user")


@dataclass
class AccountViews:
    proxy: ProxyJSON
    base_url: Callable[[], str]
    resolved_auth: RequestAuthorization
    cache: MutableMapping[str, tuple[float, JsonObject]]
    clock: Callable[[], float]
    cache_ttl: Callable[[], float]
    cache_key: Callable[[str], str]
    degraded: Callable[[str], JsonObject]
    legacy_overview: Callable[[str], Awaitable[JsonObject]]
    merge_live: Callable[[JsonObject, JsonObject], None]
    needs_live_merge: Callable[[JsonObject | None], bool]
    refresh_wallet: RefreshWallet
    degraded_catalog: Callable[[Any, str], JsonObject]
    error_message: Callable[[Any, int], str]
    logger: Logger

    def degraded_overview(self, message: str) -> dict[str, Any]:
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
            "market_base_url": self.base_url(),
        }

    async def overview(self, request: Request, body: dict[str, Any]) -> Any:
        try:
            authorization = await self.resolved_auth(request, body)
        except RECOVERABLE_ERRORS as exc:
            self.logger.exception("market_account_overview: resolve authorization failed")
            return {"success": True, "data": self.degraded(f"读取市场令牌失败：{exc}")}
        if not authorization:
            return JSONResponse(
                {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
                status_code=401,
            )
        cache_key = self.cache_key(authorization)
        if not bool(body.get("refresh")):
            cached = self.cache.get(cache_key)
            if cached is not None:
                stored_at, cached_data = cached
                if self.clock() - stored_at <= self.cache_ttl():
                    cached_overview = dict(cached_data)
                    cached_overview.setdefault("market_base_url", self.base_url())
                    return {"success": True, "data": cached_overview}
                self.cache.pop(cache_key, None)
        try:
            payload = await self.proxy(
                "GET",
                "/api/account/bootstrap",
                authorization=authorization,
                return_error_payload=True,
            )
            data: dict[str, Any] | None = None
            sync_warning = ""
            if isinstance(payload, JSONResponse):
                try:
                    import json as _json

                    proxy_body = _json.loads(bytes(payload.body).decode() if payload.body else "{}")
                    err = str(
                        proxy_body.get("message") or proxy_body.get("detail") or "市场服务不可用"
                    )
                except RECOVERABLE_ERRORS:
                    err = "市场服务不可用"
                data = self.degraded(err)
                sync_warning = err
            elif isinstance(payload, dict) and (not payload.get("__proxy_error__")):
                raw = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                data = dict(raw) if isinstance(raw, dict) else None
                if isinstance(data, dict):
                    if self.needs_live_merge(data):
                        live = await self.legacy_overview(authorization)
                        if isinstance(live, dict) and (not live.get("__proxy_error__")):
                            self.merge_live(data, live)
                        elif isinstance(live, dict) and live.get("__proxy_error__"):
                            sync_warning = self.error_message(
                                live.get("payload"), int(live.get("status_code") or 502)
                            )
            if data is None:
                legacy = await self.legacy_overview(authorization)
                if isinstance(legacy, dict) and (not legacy.get("__proxy_error__")):
                    data = legacy
                else:
                    err = ""
                    if isinstance(legacy, dict) and legacy.get("__proxy_error__"):
                        err = self.error_message(
                            legacy.get("payload"), int(legacy.get("status_code") or 502)
                        )
                    elif isinstance(payload, dict) and payload.get("__proxy_error__"):
                        err = self.error_message(
                            payload.get("payload"), int(payload.get("status_code") or 502)
                        )
                    else:
                        err = "无法连接修茈市场服务器"
                    data = self.degraded(err)
                    self.logger.warning(
                        "market_account_overview degraded: %s (base=%s)", err, self.base_url()
                    )
            if not isinstance(data, dict):
                data = self.degraded("市场账户概览返回格式异常")
            sync_warning = await self.refresh_wallet(
                data,
                authorization,
                sync_warning,
                proxy_json=self.proxy,
                error_message=self.error_message,
            )
            data = {**data, "market_base_url": self.base_url()}
            if sync_warning and (not data.get("sync_warning")):
                data["sync_warning"] = sync_warning
            self.cache[cache_key] = (self.clock(), dict(data))
            return {"success": True, "data": data}
        except RECOVERABLE_ERRORS as exc:
            self.logger.exception("market_account_overview failed")
            return {"success": True, "data": self.degraded(f"账户概览异常：{exc}")}

    async def catalog(self, request: Request, body: dict[str, Any]) -> Any:
        authorization = await self.resolved_auth(request, body)
        if not authorization:
            return JSONResponse(
                {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
                status_code=401,
            )
        refresh = "1" if bool(body.get("refresh")) else "0"
        payload = await self.proxy(
            "GET",
            f"/api/llm/catalog?refresh={refresh}",
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse):
            return self.degraded_catalog(payload, self.base_url())
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 502)
            raw_error = payload.get("payload")
            msg = self.error_message(raw_error, status_code)
            return {
                "success": True,
                "data": {
                    "degraded": True,
                    "providers": [],
                    "sync_warning": msg,
                    "market_base_url": self.base_url(),
                },
            }
        if not isinstance(payload, dict):
            return {
                "success": True,
                "data": {
                    "degraded": True,
                    "providers": [],
                    "sync_warning": "模型目录返回格式异常",
                    "market_base_url": self.base_url(),
                },
            }
        return {"success": True, "data": {**payload, "market_base_url": self.base_url()}}

    async def legacy(self, authorization: str) -> dict[str, Any]:
        """Compose account overview from older market APIs when /api/account/bootstrap is not deployed."""
        me = await self.proxy(
            "GET", "/api/auth/me", authorization=authorization, return_error_payload=True
        )
        if isinstance(me, dict) and me.get("__proxy_error__"):
            return me
        wallet = await self.proxy(
            "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
        )
        if isinstance(wallet, dict) and wallet.get("__proxy_error__"):
            balance = await self.proxy(
                "GET", "/api/wallet/balance", authorization=authorization, return_error_payload=True
            )
            wallet_data = (
                {}
                if isinstance(balance, dict) and balance.get("__proxy_error__")
                else {"wallet": balance}
            )
        else:
            wallet_data = wallet if isinstance(wallet, dict) else {}
        plan = await self.proxy(
            "GET", "/api/payment/my-plan", authorization=authorization, return_error_payload=True
        )
        plan_data = (
            {}
            if isinstance(plan, dict) and plan.get("__proxy_error__")
            else plan
            if isinstance(plan, dict)
            else {}
        )
        llm = await self.proxy(
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
            wallet_data.get("wallet")
            if isinstance(wallet_data.get("wallet"), dict)
            else wallet_data
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
