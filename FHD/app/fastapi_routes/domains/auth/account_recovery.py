"""Local email lookup and market-verified password recovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from fastapi.responses import JSONResponse
from sqlalchemy import func

from app.db.models.user import User
from app.domain.auth.ports import (
    Database,
    ErrorTypes,
    JsonObject,
    PasswordBackend,
    RouteResult,
)
from app.http.error_codes import (
    INVALID_INPUT,
    MARKET_RESET_FAILED,
    SEND_CODE_FAILED,
    WEAK_PASSWORD,
    error_envelope,
)


@dataclass(frozen=True)
class AccountRecovery:
    database: Database
    backend: Callable[[], PasswordBackend]
    normalize_email: Callable[[str], str]
    find_users: Callable[[str], list[User]]
    sync_passwords: Callable[[str, str], int]
    send_local_code: Callable[[str], JsonObject | None]
    send_market_code: Callable[[str], Awaitable[JsonObject]]
    reset_market_password: Callable[[str, str, str], Awaitable[JsonObject]]
    recoverable_errors: ErrorTypes

    def find_local_users(self, email: str) -> list[User]:
        norm = self.normalize_email(email)
        if not norm or "@" not in norm:
            return []
        with self.database() as db:
            return cast(
                "list[User]",
                db.query(User)
                .filter(func.lower(User.email) == norm)
                .filter(User.is_active.is_(True))
                .order_by(User.id.asc())
                .all(),
            )

    def sync_local_passwords(self, email: str, new_password: str) -> int:
        auth_app_service = self.backend()
        updated = 0
        for user in self.find_users(email):
            result = auth_app_service.reset_password(int(user.id), new_password)
            if result.get("success"):
                updated += 1
        return updated

    def find_account(self, body: JsonObject) -> RouteResult:
        """Look up local PostgreSQL users by email (same DB as login)."""
        email = self.normalize_email(str(body.get("email") or ""))
        if not email or "@" not in email:
            return JSONResponse(error_envelope(INVALID_INPUT, "请填写有效邮箱"), status_code=400)
        users = self.find_users(email)
        usernames = [str(u.username) for u in users if u.username]
        if usernames:
            message = f"找到 {len(usernames)} 个与本机数据库关联的账号"
        else:
            message = "本机数据库中未找到该邮箱对应的账号，可尝试注册或联系管理员"
        return {
            "success": True,
            "message": message,
            "data": {"usernames": usernames, "found": bool(usernames)},
        }

    async def send_code(self, body: JsonObject) -> RouteResult:
        """Send reset code via Xiuci market API; uses XCAGI_MARKET_BASE_URL (e.g. production server)."""
        email = self.normalize_email(str(body.get("email") or ""))
        if not email or "@" not in email:
            return JSONResponse(error_envelope(INVALID_INPUT, "请填写有效邮箱"), status_code=400)
        local_users = self.find_users(email)
        try:
            local_result = self.send_local_code(email)
            if local_result and local_result.get("success"):
                return {
                    "success": True,
                    "message": local_result.get("message", "若该邮箱已注册，将收到验证码"),
                    "data": {"local_user_count": len(local_users)},
                }
        except self.recoverable_errors():
            pass
        result = await self.send_market_code(email)
        if not result.get("success"):
            hint = result.get("message", "发送失败")
            if local_users:
                hint = f"{hint}（本机库中有该邮箱用户，请确认修茈市场服务与邮件配置正常）"
            return JSONResponse(error_envelope(SEND_CODE_FAILED, hint), status_code=502)
        return {
            "success": True,
            "message": result.get("message", "若该邮箱已注册，将收到验证码"),
            "data": {
                "market_base_url": result.get("market_base_url"),
                "local_user_count": len(local_users),
            },
        }

    async def reset_password(self, body: JsonObject) -> RouteResult:
        """Reset password on market, then sync matching users in local PostgreSQL."""
        email = self.normalize_email(str(body.get("email") or ""))
        code = str(body.get("code") or body.get("verification_code") or "").strip()
        new_password = str(body.get("new_password") or body.get("password") or "")
        if not email or "@" not in email:
            return JSONResponse(error_envelope(INVALID_INPUT, "请填写有效邮箱"), status_code=400)
        if len(new_password) < 6:
            return JSONResponse(
                error_envelope(WEAK_PASSWORD, "新密码至少 6 个字符"), status_code=400
            )
        market_result = await self.reset_market_password(email, code, new_password)
        if not market_result.get("success"):
            return JSONResponse(
                error_envelope(MARKET_RESET_FAILED, market_result.get("message", "重置失败")),
                status_code=400,
            )
        local_updated = self.sync_passwords(email, new_password)
        return {
            "success": True,
            "message": "密码已重置，请使用新密码登录",
            "data": {"local_users_updated": local_updated},
        }


def optional_local_reset_code(backend: PasswordBackend, email: str) -> JsonObject | None:
    """Adapt the optional legacy reset-code extension without making it a required backend method."""
    send = getattr(backend, "send_password_reset_code", None)
    if not callable(send):
        return None
    result = send(email)
    return result if isinstance(result, dict) else None


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()
