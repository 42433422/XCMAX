"""Registration gates, local account creation, and tenant provisioning."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.session_account_meta import AccountKind
from app.db.models.user import User
from app.domain.auth.ports import (
    AttachCookie,
    Database,
    ErrorTypes,
    JitCreate,
    JsonObject,
    LoginBackend,
    MarketPasswordLogin,
    RegistrationEnricher,
    RouteResult,
    UserDirectory,
)
from app.http.error_codes import (
    CREATE_FAILED,
    INVALID_INPUT,
    LOCAL_LOGIN_AFTER_REGISTER,
    LOGIN_AFTER_REGISTER,
    MARKET_REGISTER_FAILED,
    REGISTRATION_DISABLED,
    WEAK_PASSWORD,
    error_envelope,
)


@dataclass(frozen=True)
class Registration:
    backend: Callable[[], LoginBackend]
    directory: Callable[[], UserDirectory]
    database: Database
    product_sku: Callable[[], str | None]
    register_market: Callable[[str, str, str, str], Awaitable[JsonObject]]
    login_market: MarketPasswordLogin
    save_market_token: Callable[[str, str, str | None], None]
    pending_registration: Callable[[JsonObject], JsonObject]
    market_email: Callable[[object], str]
    jit_create: JitCreate
    open_allowed: Callable[[str], bool]
    enrich_result: RegistrationEnricher
    bind_tenant: Callable[[int, str, str], JsonObject]
    normalize_kind: Callable[[object, str], AccountKind]
    persist_meta: Callable[[str, AccountKind, str, int | None], None]
    apply_profile: Callable[[str, str, str, str], None]
    hash_password: Callable[[str], str]
    utc_now: Callable[[], datetime]
    attach_cookie: AttachCookie
    infra_errors: ErrorTypes
    logger: Logger

    def create_local_user(self, username: str, password: str, email: str) -> bool:
        try:
            with self.database() as db:
                if db.query(User).filter(User.username == username).first():
                    return False
                db.add(
                    User(
                        username=username,
                        password=self.hash_password(password),
                        display_name=username,
                        email=email or "",
                        role="user",
                        is_active=True,
                        mfa_enabled=False,
                        created_at=self.utc_now(),
                    )
                )
                db.commit()
            return True
        except self.infra_errors() as exc:
            self.logger.exception(
                "_jit_create_local_user_for_enterprise failed for %s: %s", username, exc
            )
            return False

    def enrich_tenant(
        self,
        *,
        result: dict[str, Any],
        username: str,
        session_id: str | None,
        sku: str,
        company_brand: str,
    ) -> JsonObject:
        """注册成功后创建试用租户并写入会话元数据（与登录流 bind_tenant_for_login 对齐）。"""
        user_id = (result.get("user") or {}).get("id")
        if user_id is None:
            return result
        try:
            tenant_info = self.bind_tenant(int(user_id), company_brand or username, username)
            if tenant_info.get("tenant_id") is not None:
                result["tenant_id"] = tenant_info["tenant_id"]
            if tenant_info.get("tenant_name"):
                result["tenant_name"] = tenant_info["tenant_name"]
            if session_id:
                account_kind = self.normalize_kind(
                    "enterprise" if sku == "enterprise" else "personal", "enterprise"
                )
                self.persist_meta(
                    str(session_id),
                    account_kind,
                    company_brand or "",
                    int(tenant_info["tenant_id"]) if tenant_info.get("tenant_id") else None,
                )
                result.setdefault("account_kind", account_kind)
        except self.infra_errors():
            self.logger.exception("register tenant provision failed for user_id=%s", user_id)
        return result

    async def register(self, request: Request, body: JsonObject) -> RouteResult:
        """Register locally (PostgreSQL users) and optionally on Xiuci market; then create session."""
        from app.db.bootstrap.guarded import enabled

        if enabled():
            return JSONResponse(
                {"success": False, "message": "Guarded serving does not provision accounts"},
                status_code=409,
            )
        username = (body.get("username") or "").strip()
        password = body.get("password", "")
        email = (body.get("email") or "").strip()
        verification_code = str(body.get("verification_code") or body.get("code") or "").strip()
        industry_id = (body.get("industry_id") or "").strip()
        budget_range = (body.get("budget_range") or "").strip()
        if not username or not password:
            return JSONResponse(
                error_envelope(INVALID_INPUT, "用户名和密码不能为空"), status_code=400
            )
        if len(password) < 6:
            return JSONResponse(error_envelope(WEAK_PASSWORD, "密码至少 6 个字符"), status_code=400)
        sku = self.product_sku() or "generic"
        auth_app_service = self.backend()
        if sku == "enterprise":
            reg_email = email
            market_reg = await self.register_market(
                username, password, reg_email, verification_code
            )
            if not market_reg.get("success"):
                return JSONResponse(
                    error_envelope(
                        MARKET_REGISTER_FAILED, market_reg.get("message", "修茈市场注册失败")
                    ),
                    status_code=400,
                )
            if not bool(market_reg.get("desktop_access")):
                payload = self.pending_registration(market_reg)
                return JSONResponse(payload)
            email_market = self.market_email(market_reg.get("raw")) or reg_email
            self.jit_create(username, password, email_market)
            result = auth_app_service.login(username, password)
            if not result.get("success"):
                return JSONResponse(
                    error_envelope(
                        LOCAL_LOGIN_AFTER_REGISTER, result.get("message", "注册成功但本地登录失败")
                    ),
                    status_code=500,
                )
            session_id = result.get("session_id")
            mtok = str(market_reg.get("token") or "").strip()
            mrefresh = str(market_reg.get("refresh_token") or "").strip()
            if session_id and mtok:
                self.save_market_token(str(session_id), mtok, mrefresh or None)
                result["market_access_token"] = mtok
                if mrefresh:
                    result["market_refresh_token"] = mrefresh
            result = self.enrich_result(
                result=result,
                username=username,
                session_id=str(session_id) if session_id else None,
                sku=sku,
                company_brand=email_market or email,
            )
        else:
            if not self.open_allowed(sku):
                return JSONResponse(
                    error_envelope(
                        REGISTRATION_DISABLED, "本部署未开放自助注册，请联系管理员创建账号"
                    ),
                    status_code=403,
                )
            user_service = self.directory()
            created = user_service.create_user(
                username=username,
                password=password,
                display_name=body.get("display_name") or username,
                email=email,
                role="viewer",
            )
            if not created.get("success"):
                msg = created.get("message", "创建用户失败")
                if "已存在" in msg or "unique" in msg.lower():
                    msg = "用户名已存在"
                return JSONResponse(error_envelope(CREATE_FAILED, msg), status_code=400)
            result = auth_app_service.login(username, password)
            if not result.get("success"):
                return JSONResponse(
                    error_envelope(
                        LOGIN_AFTER_REGISTER, result.get("message", "注册成功但登录失败")
                    ),
                    status_code=500,
                )
            session_id = result.get("session_id")
            try:
                market_result = await self.login_market(username, password)
                if market_result.get("success"):
                    mtok = str(market_result.get("token") or "").strip()
                    mrefresh = str(market_result.get("refresh_token") or "").strip()
                    if session_id and mtok:
                        self.save_market_token(str(session_id), mtok, mrefresh or None)
                        result["market_access_token"] = mtok
                        if mrefresh:
                            result["market_refresh_token"] = mrefresh
            except self.infra_errors():
                self.logger.exception("optional market sync after local register failed")
            result = self.enrich_result(
                result=result,
                username=username,
                session_id=str(session_id) if session_id else None,
                sku=sku,
                company_brand=email or username,
            )
        self.apply_profile(
            username, "enterprise" if sku == "enterprise" else "personal", industry_id, budget_range
        )
        payload = {"success": True, **result}
        return self.attach_cookie(JSONResponse(payload), result.get("session_id"))


def market_user_email(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    user = raw.get("user")
    if isinstance(user, dict) and user.get("email"):
        return str(user.get("email") or "").strip()
    data = raw.get("data")
    if isinstance(data, dict):
        inner = data.get("user")
        if isinstance(inner, dict) and inner.get("email"):
            return str(inner.get("email") or "").strip()
    return ""


def open_registration_allowed(sku: str, environ: Mapping[str, str]) -> bool:
    raw = (environ.get("FHD_ALLOW_OPEN_REGISTRATION") or "").strip().lower()
    if raw in {"0", "false", "no"}:
        return False
    if raw in {"1", "true", "yes"}:
        return True
    return sku != "enterprise"
