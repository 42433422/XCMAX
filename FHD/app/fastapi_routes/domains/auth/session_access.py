"""Session identity, validity, account metadata, and logout orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi import BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse

from app.db.models.user import User
from app.http.error_codes import (
    ACCOUNT_DISABLED,
    INVALID_INPUT,
    INVALID_SESSION,
    MARKET_NOT_BOUND,
    NO_SESSION,
    UNAUTHORIZED,
    error_envelope,
)

from .ports import (
    ErrorTypes,
    JsonObject,
    RouteResult,
    SessionBackend,
)


@dataclass(frozen=True)
class SessionAccess:
    resolve_user: Callable[[Request], User | None]
    session_id: Callable[[Request], str | None]
    backend: Callable[[], SessionBackend]
    desktop_gate: Callable[[str | None], JsonObject | None]
    load_meta: Callable[[str], JsonObject | None]
    enrich_meta: Callable[[str, User], JsonObject]
    session_meta: Callable[[Request, User | None], JsonObject]
    public_user: Callable[[User], JsonObject]
    profile_fields: Callable[[User | None, JsonObject], JsonObject]
    owner_permission: Callable[[User], bool]
    product_sku: Callable[[], str | None]
    market_token: Callable[[str], Awaitable[str | None]]
    sync_entitlements: Callable[[str], Awaitable[set[str]]]
    cached_entitlements: Callable[[], set[str] | None]
    subscription: Callable[[int], JsonObject]
    refresh_tokens: Callable[[str], JsonObject | None]
    clear_market_token: Callable[[str], None]
    clear_entitlements: Callable[[], None]
    remove_cookie: Callable[[Response], Response]
    infra_errors: ErrorTypes
    logger: Logger

    def metadata(self, request: Request, user: User | None) -> JsonObject:
        sid = self.session_id(request)
        if not sid:
            return {}
        if user is not None:
            return self.enrich_meta(sid, user)
        meta = self.load_meta(sid)
        return meta if meta else {}

    def current_user(self, request: Request) -> RouteResult:
        denied = self.desktop_gate(self.session_id(request))
        if denied is not None:
            return JSONResponse(denied, status_code=403)
        user = self.resolve_user(request)
        if not user:
            return JSONResponse(
                {**error_envelope(UNAUTHORIZED, "请先登录"), "valid": False}, status_code=200
            )
        if not getattr(user, "is_active", True):
            return JSONResponse(error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403)
        auth_app_service = self.backend()
        permissions = auth_app_service.get_user_permissions(user)
        session_meta = self.session_meta(request, user)
        tenant_is_owner = (
            bool(session_meta.get("market_is_enterprise"))
            and (not session_meta.get("market_is_admin"))
            and (session_meta.get("impersonating_market_user_id") is None)
            and (user.market_user_id is not None)
            and (session_meta.get("market_user_id") == user.market_user_id)
            and self.owner_permission(user)
        )
        return {
            "success": True,
            "data": {
                "user": self.public_user(user),
                "permissions": permissions,
                "tenant_is_owner": tenant_is_owner,
                "account_kind": session_meta.get("account_kind") or "enterprise",
                "company_brand": session_meta.get("company_brand") or "",
                "market_is_admin": bool(session_meta.get("market_is_admin")),
                "market_is_enterprise": bool(session_meta.get("market_is_enterprise")),
                "market_user_id": session_meta.get("market_user_id"),
                "local_user_id": session_meta.get("local_user_id") or getattr(user, "id", None),
                "tenant_id": session_meta.get("tenant_id"),
                "tenant_name": session_meta.get("tenant_name")
                or session_meta.get("company_brand")
                or "",
                "impersonating_market_user_id": session_meta.get("impersonating_market_user_id"),
                "impersonating_username": session_meta.get("impersonating_username") or "",
                **self.profile_fields(user, session_meta),
            },
        }

    async def _refresh_entitlements(self, session_id: str) -> None:
        """Expose an async task even when the injected port is a late-bound callable."""
        await self.sync_entitlements(session_id)

    async def validate(self, request: Request, background_tasks: BackgroundTasks) -> RouteResult:
        session_id = self.session_id(request)
        if not session_id:
            return JSONResponse(
                {**error_envelope(NO_SESSION, "无会话信息"), "valid": False}, status_code=200
            )
        denied = self.desktop_gate(session_id)
        if denied is not None:
            return JSONResponse(denied, status_code=403)
        auth_app_service = self.backend()
        session_info = auth_app_service.session_manager.get_session_info(session_id)
        if not session_info:
            return JSONResponse(
                {**error_envelope(INVALID_SESSION, "会话无效或已过期"), "valid": False},
                status_code=200,
            )
        user = self.resolve_user(request)
        if user is not None and getattr(user, "is_active", True) is False:
            return JSONResponse(
                {**error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), "valid": False},
                status_code=403,
            )
        try:
            if self.product_sku() == "enterprise":
                market_tok = await self.market_token(session_id)
                if not market_tok:
                    return JSONResponse(
                        {
                            **error_envelope(
                                MARKET_NOT_BOUND,
                                "企业版需使用修茈市场企业级账号登录。若此前仅用本地管理员进入，请退出后重新登录。",
                            ),
                            "valid": False,
                        },
                        status_code=200,
                    )
        except self.infra_errors():
            self.logger.exception("enterprise market session check on validate failed")
        entitled_mod_ids: list[str] = []
        try:
            background_tasks.add_task(self._refresh_entitlements, session_id)
            cached = self.cached_entitlements()
            if cached is not None:
                entitled_mod_ids = sorted(cached)
        except self.infra_errors():
            self.logger.exception("sync enterprise entitlements on validate failed")
        session_meta = self.session_meta(request, user)
        payload: dict[str, Any] = {"success": True, "valid": True, "data": session_info}
        if entitled_mod_ids:
            payload["entitled_mod_ids"] = entitled_mod_ids
        if session_meta:
            payload["account_kind"] = session_meta.get("account_kind")
            payload["company_brand"] = session_meta.get("company_brand")
            payload["market_is_admin"] = session_meta.get("market_is_admin")
            payload["market_is_enterprise"] = session_meta.get("market_is_enterprise")
            payload["market_user_id"] = session_meta.get("market_user_id")
            payload["local_user_id"] = session_meta.get("local_user_id")
            payload["tenant_id"] = session_meta.get("tenant_id")
            payload["tenant_name"] = session_meta.get("tenant_name")
            payload["impersonating_market_user_id"] = session_meta.get(
                "impersonating_market_user_id"
            )
            payload["impersonating_username"] = session_meta.get("impersonating_username")
            payload.update(self.profile_fields(user, session_meta))
        return payload

    def subscription_status(self, request: Request) -> RouteResult:
        """当前登录用户的试用/付费订阅状态（SaasPricingView 与订阅门禁共用）。"""
        user = self.resolve_user(request)
        if not user:
            return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
        if getattr(user, "is_active", True) is False:
            return JSONResponse(error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403)
        status = self.subscription(int(user.id))
        return {"success": True, "data": status}

    def refresh(self, body: JsonObject) -> RouteResult:
        """无状态 JWT：用 refresh token 轮转出新的 access/refresh（一次性使用）。"""
        rt = str(body.get("refresh_token") or "").strip()
        tokens = self.refresh_tokens(rt)
        if not tokens:
            return JSONResponse(
                error_envelope(INVALID_INPUT, "refresh token 无效或已使用"), status_code=401
            )
        return {"success": True, "data": tokens}

    def logout(self, request: Request) -> RouteResult:
        sid = self.session_id(request)
        if not sid:
            return JSONResponse(error_envelope(NO_SESSION, "无有效会话"), status_code=400)
        auth_app_service = self.backend()
        result = auth_app_service.logout(sid)
        self.clear_market_token(sid)
        try:
            self.clear_entitlements()
        except self.infra_errors():
            pass
        resp = JSONResponse(result)
        return self.remove_cookie(resp)

    def runtime_sku(self) -> RouteResult:
        sku = self.product_sku()
        return {
            "success": True,
            "data": {"sku": sku or "generic", "is_enterprise_edition": sku == "enterprise"},
        }


def account_profile_fields(user: User | None, session_meta: dict[str, Any]) -> JsonObject:
    """账号体系真相源字段（暴露给前端只读展示）：tier / account_tier / budget_range /
    entitled_industries / market_membership_tier。account_tier 经派生（非企业为 None）。"""
    from app.domain.catalog.account_tier_derivation import resolve_account_tier_for_user

    tier = str(getattr(user, "tier", "") or "") if user is not None else ""
    return {
        "tier": tier or None,
        "account_tier": resolve_account_tier_for_user(tier, getattr(user, "account_tier", None)),
        "budget_range": getattr(user, "budget_range", None) if user is not None else None,
        "entitled_industries": list(getattr(user, "entitled_industries", None) or []),
        "market_membership_tier": session_meta.get("market_membership_tier"),
        "email_verified": bool(getattr(user, "email_verified", False))
        if user is not None
        else False,
        "mfa_enabled": bool(getattr(user, "mfa_enabled", False)) if user is not None else False,
    }
