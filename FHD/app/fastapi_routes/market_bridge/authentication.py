"""Registration, login and verification against the canonical market identity service."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

from app.application.market_bridge.protocols import DemoPayload, JsonObject, NormalizeAuth, ProxyJSON


@dataclass
class Authentication:
    proxy: ProxyJSON
    base_url: Callable[[], str]
    error_message: Callable[[Any, int], str]
    normalize_auth: NormalizeAuth
    user_id: Callable[[Any], int | None]
    try_demo: Callable[[str, str], JsonObject | None]
    is_local_base: Callable[[str], bool]
    demo_payload: DemoPayload

    async def password_login(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate against the market server and return a normalized token payload."""
        market_base = self.base_url()
        demo_shim = self.try_demo(username, password)
        if demo_shim and self.is_local_base(market_base):
            return self.demo_payload(demo_shim, market_base_url=market_base)
        payload = await self.proxy(
            "POST", "/api/auth/login", json_body={"username": username, "password": password}
        )
        if isinstance(payload, JSONResponse):
            try:
                status_code = int(payload.status_code or 502)
            except (TypeError, ValueError):
                status_code = 502
            if demo_shim and self.is_local_base(market_base) and (status_code >= 400):
                return self.demo_payload(demo_shim, market_base_url=market_base)
        result = await self.normalize_auth(payload, market_base=market_base)
        if not result.get("success") and demo_shim and self.is_local_base(market_base):
            sc = int(result.get("status_code") or 502)
            if sc >= 400:
                return self.demo_payload(demo_shim, market_base_url=market_base)
        return result

    async def phone_login(self, phone: str, code: str) -> dict[str, Any]:
        """Authenticate against market via phone verification code."""
        market_base = self.base_url()
        payload = await self.proxy(
            "POST",
            "/api/auth/login-with-phone-code",
            json_body={"phone": (phone or "").strip(), "code": (code or "").strip()},
        )
        return await self.normalize_auth(payload, market_base=market_base)

    async def register(
        self, username: str, password: str, email: str, verification_code: str = ""
    ) -> dict[str, Any]:
        """Register on the configured Xiuci market server. Returns success/message/token/raw."""
        register_body = {
            "username": username,
            "password": password,
            "email": email,
            "verification_code": (verification_code or "").strip(),
        }
        payload = await self.proxy(
            "POST", "/api/auth/register", json_body=register_body, return_error_payload=True
        )
        if isinstance(payload, JSONResponse):
            return {"success": False, "message": "市场服务不可用"}
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 400)
            raw_error = payload.get("payload")
            if status_code >= 400:
                return {
                    "success": False,
                    "message": self.error_message(raw_error, status_code),
                    "raw": raw_error,
                }
        normalized = await self.normalize_auth(payload)
        normalized["market_user_id"] = self.user_id(payload)
        return normalized

    async def send_register_code(self, email: str) -> dict[str, Any]:
        """Request a registration code from the canonical market identity service."""
        email_norm = (email or "").strip().lower()
        if not email_norm or "@" not in email_norm:
            return {"success": False, "message": "请填写有效邮箱", "status_code": 400}
        payload = await self.proxy(
            "POST",
            "/api/auth/send-register-code",
            json_body={"email": email_norm},
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse):
            return {"success": False, "message": "市场服务不可用", "status_code": 502}
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 502)
            raw = payload.get("payload")
            return {
                "success": False,
                "message": self.error_message(raw, status_code) or "发送验证码失败",
                "status_code": status_code,
            }
        message = str(payload.get("message") or "") if isinstance(payload, dict) else ""
        return {"success": True, "message": message or "验证码已发送"}

    async def send_reset_code(self, email: str) -> dict[str, Any]:
        """Request password-reset verification email from the configured market server."""
        email_norm = (email or "").strip().lower()
        if not email_norm or "@" not in email_norm:
            return {"success": False, "message": "请填写有效邮箱"}
        payload = await self.proxy(
            "POST",
            "/api/auth/send-reset-password-code",
            json_body={"email": email_norm},
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse):
            return {"success": False, "message": "市场服务不可用"}
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 502)
            raw = payload.get("payload")
            return {
                "success": False,
                "message": self.error_message(raw, status_code) or "无法连接修茈市场发送验证码",
                "market_base_url": self.base_url(),
            }
        msg = ""
        if isinstance(payload, dict):
            msg = str(payload.get("message") or "").strip()
        return {
            "success": True,
            "message": msg or "若该邮箱已注册，将收到验证码邮件",
            "market_base_url": self.base_url(),
            "raw": payload,
        }

    async def reset_password(self, email: str, code: str, new_password: str) -> dict[str, Any]:
        """Reset password on market server using email verification code."""
        email_norm = (email or "").strip().lower()
        code_s = (code or "").strip()
        if not email_norm or "@" not in email_norm:
            return {"success": False, "message": "请填写有效邮箱"}
        if len(code_s) < 4:
            return {"success": False, "message": "请填写验证码"}
        if len(new_password or "") < 6:
            return {"success": False, "message": "新密码至少 6 个字符"}
        payload = await self.proxy(
            "POST",
            "/api/auth/reset-password",
            json_body={"email": email_norm, "code": code_s, "new_password": new_password},
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse):
            return {"success": False, "message": "市场服务不可用"}
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 400)
            raw = payload.get("payload")
            return {
                "success": False,
                "message": self.error_message(raw, status_code) or "重置失败",
                "raw": raw,
            }
        if isinstance(payload, dict) and payload.get("success") is False:
            return {
                "success": False,
                "message": str(payload.get("message") or payload.get("detail") or "重置失败"),
                "raw": payload,
            }
        return {"success": True, "message": "密码已重置", "raw": payload}

    async def send_phone_code(self, phone: str) -> dict[str, Any]:
        """Proxy send-phone-code to market."""
        payload = await self.proxy(
            "POST", "/api/auth/send-phone-code", json_body={"phone": (phone or "").strip()}
        )
        if isinstance(payload, JSONResponse):
            try:
                raw_body = json.loads(bytes(payload.body).decode("utf-8") if payload.body else "{}")
            except RECOVERABLE_ERRORS:
                raw_body = {}
            return {
                "success": False,
                "message": str(
                    raw_body.get("message") or raw_body.get("detail") or "发送验证码失败"
                ),
                "status_code": int(payload.status_code or 502),
            }
        if isinstance(payload, dict):
            return {"success": True, "message": str(payload.get("message") or "验证码已发送")}
        return {"success": True, "message": "验证码已发送"}
