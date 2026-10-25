"""Password and phone-code entry points into the verified market-first flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger

from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.application.session_account_meta import AccountKind
from app.http.error_codes import (
    INVALID_INPUT,
    error_envelope,
)

from .port_contracts import (
    AttachCookie,
    ErrorTypes,
    JitCreate,
    JsonObject,
    LoginBackend,
    MarketFirstLogin,
    MarketPasswordLogin,
    RouteResult,
)


@dataclass(frozen=True)
class CredentialLogin:
    backend: Callable[[], LoginBackend]
    product_sku: Callable[[], str | None]
    normalize_kind: Callable[[object, str], AccountKind]
    run_login: MarketFirstLogin
    login_market: MarketPasswordLogin
    login_phone: Callable[[str, str], Awaitable[JsonObject]]
    jit_create: JitCreate
    market_email: Callable[[object], str]
    issue_tokens: Callable[[int, str, str, str], JsonObject]
    attach_cookie: AttachCookie
    clock: Callable[[], float]
    observe_login: Callable[[str, float], None]
    infra_errors: ErrorTypes
    logger: Logger

    async def password(
        self, request: Request, body: JsonObject, background_tasks: BackgroundTasks | None
    ) -> RouteResult:
        login_start = self.clock()
        username = (body.get("username") or "").strip()
        password = body.get("password", "")
        if not username or not password:
            self.observe_login("password", self.clock() - login_start)
            return JSONResponse(
                error_envelope(INVALID_INPUT, "用户名和密码不能为空"), status_code=200
            )
        auth_app_service = self.backend()
        sku = self.product_sku() or "personal"
        account_kind = self.normalize_kind(
            body.get("account_kind"), "enterprise" if sku == "enterprise" else "personal"
        )
        result, err = await self.run_login(
            username=username,
            password=password,
            account_kind=account_kind,
            market_result=None,
            auth_app_service=auth_app_service,
            sku=sku,
            jit_create_fn=self.jit_create,
            market_user_email_from_raw=self.market_email,
            login_market_fn=self.login_market,
            background_tasks=background_tasks,
            totp_code=str(body.get("totp_code") or "").strip() or None,
            invitation_code=str(body.get("invitation_code") or "").strip(),
        )
        if err:
            self.observe_login("password", self.clock() - login_start)
            return err
        if result and result.get("success"):
            _u = result.get("user") or {}
            if _u.get("id") is not None:
                try:
                    result["web_tokens"] = self.issue_tokens(
                        int(_u["id"]),
                        str(_u.get("username") or ""),
                        str(result.get("account_kind") or "enterprise"),
                        str(result.get("session_id") or ""),
                    )
                except self.infra_errors():
                    self.logger.exception("issue web tokens failed")
        resp = self.attach_cookie(JSONResponse(result or {}), (result or {}).get("session_id"))
        self.observe_login("password", self.clock() - login_start)
        return resp

    async def phone_code(
        self, request: Request, body: JsonObject, background_tasks: BackgroundTasks | None
    ) -> RouteResult:
        login_start = self.clock()
        phone = str(body.get("phone") or "").strip()
        code = str(body.get("code") or "").strip()
        if not phone or not code:
            self.observe_login("phone_code", self.clock() - login_start)
            return JSONResponse(
                error_envelope(INVALID_INPUT, "手机号和验证码不能为空"), status_code=400
            )
        auth_app_service = self.backend()
        sku = self.product_sku() or "personal"
        account_kind = self.normalize_kind(
            body.get("account_kind"), "enterprise" if sku == "enterprise" else "personal"
        )
        market_result = await self.login_phone(phone, code)
        username = str(body.get("username") or "").strip()
        result, err = await self.run_login(
            username=username,
            password=None,
            account_kind=account_kind,
            market_result=market_result,
            auth_app_service=auth_app_service,
            sku=sku,
            jit_create_fn=self.jit_create,
            market_user_email_from_raw=self.market_email,
            login_market_fn=None,
            background_tasks=background_tasks,
        )
        if err:
            self.observe_login("phone_code", self.clock() - login_start)
            return err
        resp = self.attach_cookie(JSONResponse(result or {}), (result or {}).get("session_id"))
        self.observe_login("phone_code", self.clock() - login_start)
        return resp
