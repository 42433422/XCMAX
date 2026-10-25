"""Explicit development diagnostics, separate from verified public registration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi.responses import JSONResponse

from .port_contracts import ProxyJSON


@dataclass
class MarketDiagnostics:
    proxy: ProxyJSON
    base_url: Callable[[], str]
    register_open: Callable[[str, str, str], Awaitable[Any]]
    access_token: Callable[[Any], str]
    error_message: Callable[[Any, int], str]
    new_id: Callable[[], UUID]

    async def register_diagnostic(self, username: str, password: str, email: str) -> Any:
        """Use the explicitly enabled server-side API for the dev diagnostic only.

        The public registration flow never calls this helper and therefore cannot
        silently bypass email verification.
        """
        payload = await self.proxy(
            "POST",
            "/api/market/open/register",
            json_body={"username": username, "password": password, "email": email},
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            payload = await self.proxy(
                "POST",
                "/api/auth/register-open",
                json_body={"username": username, "password": password, "email": email},
                return_error_payload=True,
            )
        return payload

    async def status(self) -> Any:
        """Check whether the local backend can reach the configured Xiuci market server."""
        payload = await self.proxy("GET", "/api/health", return_error_payload=True)
        if isinstance(payload, JSONResponse):
            return payload
        reachable = not (isinstance(payload, dict) and payload.get("__proxy_error__"))
        return {
            "success": reachable,
            "data": {
                "market_base_url": self.base_url(),
                "reachable": reachable,
                "raw": payload.get("payload")
                if isinstance(payload, dict) and payload.get("__proxy_error__")
                else payload,
            },
        }

    async def create_account(self, body: dict[str, Any]) -> Any:
        """Create a market account via server-side open API and verify login/overview connectivity."""
        username = str(body.get("username") or f"xcagi_{self.new_id().hex[:10]}").strip()
        password = str(body.get("password") or self.new_id().hex[:12])
        email = str(body.get("email") or f"{username}@xcagi.local").strip()
        if len(password) < 6:
            return JSONResponse(
                {"success": False, "message": "password 至少 6 位"}, status_code=400
            )
        payload = await self.register_open(username, password, email)
        if isinstance(payload, JSONResponse):
            return payload
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status_code = int(payload.get("status_code") or 400)
            raw_error = payload.get("payload")
            if status_code == 409 or "存在" in self.error_message(raw_error, status_code):
                payload = await self.proxy(
                    "POST",
                    "/api/auth/login",
                    json_body={"username": username, "password": password},
                )
            else:
                return JSONResponse(
                    {
                        "success": False,
                        "message": self.error_message(raw_error, status_code),
                        "data": raw_error,
                    },
                    status_code=status_code,
                )
        token = self.access_token(payload)
        if not token:
            return JSONResponse(
                {"success": False, "message": "账号创建成功但未返回 token", "data": payload},
                status_code=502,
            )
        overview = await self.proxy(
            "GET", "/api/account/bootstrap", authorization=token, return_error_payload=True
        )
        return {
            "success": True,
            "data": {
                "market_base_url": self.base_url(),
                "username": username,
                "email": email,
                "password": password,
                "token": token,
                "overview_ok": not (isinstance(overview, dict) and overview.get("__proxy_error__")),
                "overview": overview.get("payload")
                if isinstance(overview, dict) and overview.get("__proxy_error__")
                else overview,
            },
        }
