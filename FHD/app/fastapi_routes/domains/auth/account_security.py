"""MFA enrollment transitions and authenticated password changes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from app.db.models.user import User
from app.http.error_codes import (
    ACCOUNT_DISABLED,
    INVALID_INPUT,
    UNAUTHORIZED,
    WEAK_PASSWORD,
    error_envelope,
)

from .ports import (
    Database,
    JsonObject,
    PasswordBackend,
    RouteResult,
)


@dataclass(frozen=True)
class AccountSecurity:
    resolve_user: Callable[[Request], User | None]
    database: Database
    backend: Callable[[], PasswordBackend]
    generate_secret: Callable[[], str]
    provisioning_uri: Callable[[str, str], str]
    verify_totp: Callable[[str, str], bool]

    def setup(self, request: Request) -> RouteResult:
        """生成 TOTP 密钥（待验证；mfa_enabled 在 /enable 校验通过后才置 True）。"""
        user = self.resolve_user(request)
        if not user:
            return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
        if getattr(user, "is_active", True) is False:
            return JSONResponse(error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403)
        with self.database() as db:
            u = db.get(User, int(user.id))
            if u is not None and u.is_active is False:
                return JSONResponse(
                    error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403
                )
            if u is None:
                return JSONResponse(error_envelope(UNAUTHORIZED, "用户不存在"), status_code=200)
            if u.mfa_enabled:
                return JSONResponse(
                    error_envelope(INVALID_INPUT, "请先验证当前动态验证码并关闭 MFA，再重新设置"),
                    status_code=409,
                )
            secret = self.generate_secret()
            u.totp_secret = secret
            db.commit()
            username = u.username
        return {
            "success": True,
            "data": {"secret": secret, "otpauth_uri": self.provisioning_uri(secret, username)},
        }

    def enable(self, request: Request, body: JsonObject) -> RouteResult:
        """校验 TOTP 后开启 MFA。"""
        user = self.resolve_user(request)
        if not user:
            return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
        if getattr(user, "is_active", True) is False:
            return JSONResponse(error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403)
        code = str(body.get("code") or body.get("totp_code") or "").strip()
        with self.database() as db:
            u = db.get(User, int(user.id))
            if u is not None and u.is_active is False:
                return JSONResponse(
                    error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403
                )
            if u is None or not (u.totp_secret or ""):
                return JSONResponse(
                    error_envelope(INVALID_INPUT, "请先调用 /api/auth/mfa/setup 生成密钥"),
                    status_code=400,
                )
            if not self.verify_totp(u.totp_secret or "", code):
                return JSONResponse(
                    error_envelope(INVALID_INPUT, "动态验证码错误"), status_code=400
                )
            u.mfa_enabled = True
            db.commit()
        return {"success": True, "message": "MFA 已开启"}

    def disable(self, request: Request, body: JsonObject) -> RouteResult:
        """关闭 MFA（已开启时需校验当前 TOTP）。"""
        user = self.resolve_user(request)
        if not user:
            return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
        if getattr(user, "is_active", True) is False:
            return JSONResponse(error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403)
        code = str(body.get("code") or body.get("totp_code") or "").strip()
        with self.database() as db:
            u = db.get(User, int(user.id))
            if u is not None and u.is_active is False:
                return JSONResponse(
                    error_envelope(ACCOUNT_DISABLED, "账户已被禁用"), status_code=403
                )
            if u is None:
                return JSONResponse(error_envelope(UNAUTHORIZED, "用户不存在"), status_code=200)
            if u.mfa_enabled and (not self.verify_totp(u.totp_secret or "", code)):
                return JSONResponse(
                    error_envelope(INVALID_INPUT, "动态验证码错误"), status_code=400
                )
            u.mfa_enabled = False
            u.totp_secret = None
            db.commit()
        return {"success": True, "message": "MFA 已关闭"}

    def change_password(self, body: JsonObject, user: User) -> RouteResult:
        old_password = body.get("old_password", "")
        new_password = body.get("new_password", "")
        if not old_password or not new_password:
            return JSONResponse(error_envelope(INVALID_INPUT, "请填写完整信息"), status_code=400)
        if len(new_password) < 6:
            return JSONResponse(
                error_envelope(WEAK_PASSWORD, "新密码至少 6 个字符"), status_code=400
            )
        auth_app_service = self.backend()
        result = auth_app_service.change_password(user.id, old_password, new_password)
        if not result["success"]:
            return JSONResponse(result, status_code=400)
        return result
