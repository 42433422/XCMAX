"""HTTP input and response contracts for market identity operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.market_bridge.protocols import JsonObject


@dataclass
class IdentityRoutes:
    register_user: Callable[[str, str, str, str], Awaitable[JsonObject]]
    password_login: Callable[[str, str], Awaitable[JsonObject]]
    phone_login: Callable[[str, str], Awaitable[JsonObject]]
    send_phone_code: Callable[[str], Awaitable[JsonObject]]
    send_register_code: Callable[[str], Awaitable[JsonObject]]
    bind_session: Callable[[Request, JsonObject], tuple[str, str]]
    base_url: Callable[[], str]

    async def register(self, request: Request, body: dict[str, Any]) -> Any:
        """Register a Xiuci market account through the configured market server."""
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        email = str(body.get("email") or "").strip()
        verification_code = str(body.get("verification_code") or body.get("code") or "").strip()
        if not username or not password:
            return JSONResponse(
                {"success": False, "message": "username、password 必填"}, status_code=400
            )
        result = await self.register_user(username, password, email, verification_code)
        if not result.get("success"):
            return JSONResponse(
                {
                    "success": False,
                    "message": result.get("message", "注册失败"),
                    "data": result.get("raw"),
                },
                status_code=400,
            )
        token, _ = self.bind_session(request, result)
        return {
            "success": True,
            "data": {
                "market_base_url": result.get("market_base_url"),
                "token": token,
                "refresh_token": result.get("refresh_token"),
                "account_state": result.get("account_state"),
                "next_action": result.get("next_action"),
                "desktop_access": bool(result.get("desktop_access")),
                "active_plan_id": result.get("active_plan_id"),
                "account_tier": result.get("account_tier"),
                "raw": result.get("raw"),
            },
        }

    async def login(self, request: Request, body: dict[str, Any]) -> Any:
        """Login to Xiuci market (username/password) and bind JWT to the current FHD session.

        Prefer ``POST /api/auth/login`` for the desktop app; this route remains for
        settings/tools that only need market credentials. Token-only bind: ``POST /account-sync``.
        """
        username = str(body.get("username") or body.get("email") or "").strip()
        password = str(body.get("password") or "")
        if not username or not password:
            return JSONResponse(
                {"success": False, "message": "username 与 password 必填"}, status_code=400
            )
        market_result = await self.password_login(username, password)
        if not market_result.get("success"):
            return JSONResponse(
                {"success": False, "message": market_result.get("message", "市场登录失败")},
                status_code=403,
            )
        token, refresh = self.bind_session(request, market_result)
        return {
            "success": True,
            "data": {
                "market_base_url": self.base_url(),
                "token": token,
                "refresh_token": refresh,
                "account_state": market_result.get("account_state"),
                "next_action": market_result.get("next_action"),
                "desktop_access": bool(market_result.get("desktop_access")),
                "active_plan_id": market_result.get("active_plan_id"),
                "account_tier": market_result.get("account_tier"),
                "raw": market_result.get("raw"),
            },
        }

    async def phone_login_route(self, body: dict[str, Any]) -> Any:
        phone = str(body.get("phone") or "").strip()
        code = str(body.get("code") or "").strip()
        if not phone or not code:
            return JSONResponse(
                {"success": False, "message": "请填写手机号和验证码"}, status_code=400
            )
        result = await self.phone_login(phone, code)
        if not result.get("success"):
            status = int(result.get("status_code") or 401)
            return JSONResponse(
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

    async def phone_code(self, body: dict[str, Any]) -> Any:
        phone = str(body.get("phone") or "").strip()
        if not phone:
            return JSONResponse({"success": False, "message": "请填写手机号"}, status_code=400)
        result = await self.send_phone_code(phone)
        if not result.get("success"):
            status = int(result.get("status_code") or 502)
            return JSONResponse(result, status_code=status if status >= 400 else 502)
        return {"success": True, "message": result.get("message") or "验证码已发送"}

    async def registration_code(self, body: dict[str, Any]) -> Any:
        result = await self.send_register_code(str(body.get("email") or ""))
        if not result.get("success"):
            status = int(result.get("status_code") or 502)
            return JSONResponse(result, status_code=status if status >= 400 else 502)
        return {"success": True, "message": result.get("message") or "验证码已发送"}
