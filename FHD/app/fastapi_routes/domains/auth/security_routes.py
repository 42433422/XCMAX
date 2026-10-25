"""Authenticated MFA setup and password changes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Body, Depends, Request

from app.db.models.user import User

from .account_security import AccountSecurity
from app.domain.auth.ports import JsonObject


class SecurityRoutes:
    """Authenticated MFA setup and password changes."""

    def __init__(
        self,
        *,
        security: Callable[[], AccountSecurity],
        authenticated_user: Callable[[Request], User],
    ) -> None:
        router = self.mfa = APIRouter()

        @router.post("/api/auth/mfa/setup", response_model=None)
        def auth_mfa_setup(request: Request) -> object:
            """生成 TOTP 密钥（待验证；mfa_enabled 在 /enable 校验通过后才置 True）。"""
            return security().setup(request)

        self.auth_mfa_setup = auth_mfa_setup

        @router.post("/api/auth/mfa/enable", response_model=None)
        def auth_mfa_enable(
            request: Request, body: JsonObject = Body(default_factory=dict)
        ) -> object:
            """校验 TOTP 后开启 MFA。"""
            return security().enable(request, body)

        self.auth_mfa_enable = auth_mfa_enable

        @router.post("/api/auth/mfa/disable", response_model=None)
        def auth_mfa_disable(
            request: Request, body: JsonObject = Body(default_factory=dict)
        ) -> object:
            """关闭 MFA（已开启时需校验当前 TOTP）。"""
            return security().disable(request, body)

        self.auth_mfa_disable = auth_mfa_disable

        router = self.password = APIRouter()

        @router.post("/api/auth/password/change", response_model=None)
        def auth_password_change(
            body: JsonObject = Body(default_factory=dict), user: User = Depends(authenticated_user)
        ) -> object:
            return security().change_password(body, user)

        self.auth_password_change = auth_password_change
