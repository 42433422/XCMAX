"""Request-scoped credential selection, authenticated handoff and session binding."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.application.market_bridge.protocols import (
    JsonObject,
    LatestToken,
    LocalUser,
    ProxyJSON,
    SaveToken,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def session_id_from_request(request: Request) -> str:
    cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session_id")
    cookies = getattr(request, "cookies", None)
    headers = getattr(request, "headers", None)
    cookie_sid = cookies.get(cookie_name) if isinstance(cookies, Mapping) else ""
    header_sid = headers.get("X-Session-ID") if isinstance(headers, Mapping) else ""
    return str(cookie_sid or header_sid or "").strip()


@dataclass
class RequestIdentity:
    session_id: Callable[[Request], str]
    access_token: Callable[[str], str]
    refresh_token: Callable[[str], str]
    latest_token: LatestToken
    user_id: Callable[[str], int | None]
    current_user: Callable[[Request], LocalUser | None]
    normalize: Callable[[str], str]
    auth_header: Callable[[str], str]
    resolve_token: Callable[[str], Awaitable[str]]
    save: SaveToken
    fallback_auth: Callable[[Request, JsonObject], str]
    base_url: Callable[[], str]
    sync_entitlements: Callable[[str], Awaitable[Any]]
    proxy: ProxyJSON
    logger: Logger

    def bind(self, request: Request, market_result: dict[str, Any]) -> tuple[str, str]:
        """Write market JWT from ``login_market_with_password`` (or register) onto the current FHD session."""
        token = str(market_result.get("token") or "").strip()
        refresh = str(market_result.get("refresh_token") or "").strip()
        sid = self.owned_session(request, self.current_owner(request))
        if sid and token:
            self.save(sid, token, refresh or None)
        return (token, refresh)

    async def refresh_entitlements(self, session_id: str) -> None:
        try:
            await self.sync_entitlements(session_id)
        except RECOVERABLE_ERRORS:
            self.logger.warning("current-session entitlement refresh unavailable")

    async def handoff(self, request: Request, background: BackgroundTasks) -> Any:
        """Return credentials only to their verified local session, for API calls.
        Browser navigation uses POST /browser-handoff. Anonymous, mismatched and
        unavailable sessions must never borrow another session's credentials.
        Entitlement refresh talks to the market and must not hold this response.
        """
        headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
        try:
            user = self.current_user(request)
            sid = self.session_id(request)
            if (
                user is None
                or getattr(user, "id", None) is None
                or (not getattr(user, "is_active", True))
                or (not sid)
                or (self.user_id(sid) != user.id)
            ):
                return JSONResponse(
                    {"success": False, "message": "请先登录当前桌面账号"},
                    status_code=401,
                    headers=headers,
                )
            tok = self.normalize(self.access_token(sid))
            if not tok:
                return JSONResponse(
                    {"success": False, "message": "当前会话未连接市场账号，请重新登录"},
                    status_code=404,
                    headers=headers,
                )
            data = {"market_access_token": tok, "market_base_url": self.base_url()}
            refresh = self.refresh_token(sid)
            if refresh:
                data["market_refresh_token"] = refresh
            background.add_task(self.refresh_entitlements, sid)
            return JSONResponse({"success": True, "data": data}, headers=headers)
        except RECOVERABLE_ERRORS:
            self.logger.warning("market session authentication unavailable")
            return JSONResponse(
                {"success": False, "message": "市场会话暂时不可用，请重试"},
                status_code=502,
                headers=headers,
            )

    def current_owner(self, request: Request) -> int | None:
        try:
            user = self.current_user(request)
            if not user or not getattr(user, "is_active", True):
                return None
            user_id = getattr(user, "id", None)
            return user_id if type(user_id) is int and user_id > 0 else None
        except RECOVERABLE_ERRORS:
            return None

    def owned_session(self, request: Request, user_id: int | None) -> str:
        sid = self.session_id(request)
        return sid if sid and user_id is not None and self.user_id(sid) == user_id else ""

    def authorization(self, request: Request, body: dict[str, Any]) -> str:
        """Current desktop session token → newest persisted token → explicit browser token.

        The browser may keep an old market JWT in localStorage while the local backend already has
        a fresh token bound to the current FHD login session. Strong account state should follow the
        backend session, not stale client storage.
        """
        user_id = self.current_owner(request)
        sid = self.owned_session(request, user_id)
        session_auth = self.auth_header(self.access_token(sid)) if sid else ""
        if session_auth:
            return session_auth
        if user_id is not None:
            latest_auth = self.auth_header(self.latest_token(user_id=user_id))
            if latest_auth:
                return latest_auth
        auth = self.auth_header(str(body.get("authorization") or body.get("token") or ""))
        if auth:
            return auth
        hdr = str(
            request.headers.get("Authorization") or request.headers.get("authorization") or ""
        ).strip()
        if hdr:
            return self.auth_header(hdr)
        return ""

    async def resolved_authorization(self, request: Request, body: dict[str, Any]) -> str:
        """Like ``_authorization_from_request`` but refreshes expired session-bound market JWTs."""
        sid = self.owned_session(request, self.current_owner(request))
        if sid:
            resolved = await self.resolve_token(sid)
            if resolved:
                return self.auth_header(resolved)
        return self.fallback_auth(request, body)

    def market_auth(self, request: Request) -> str:
        sid = self.owned_session(request, self.current_owner(request))
        tok = self.access_token(sid) if sid else ""
        if tok:
            return tok
        return str(request.headers.get("Authorization") or "").strip()

    async def sync(self, request: Request, body: dict[str, Any]) -> Any:
        authorization = self.auth_header(str(body.get("authorization") or body.get("token") or ""))
        if not authorization:
            hdr = str(
                request.headers.get("Authorization") or request.headers.get("authorization") or ""
            ).strip()
            if hdr:
                authorization = self.auth_header(hdr)
        if not authorization:
            return JSONResponse(
                {"success": False, "message": "authorization 必填"}, status_code=400
            )
        payload = await self.proxy("GET", "/api/auth/me", authorization=authorization)
        if isinstance(payload, JSONResponse):
            return payload
        sid = self.owned_session(request, self.current_owner(request))
        if sid:
            self.save(sid, self.normalize(authorization))
        data = (
            payload.get("data")
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
            else payload
        )
        user = (
            data.get("user")
            if isinstance(data, dict) and isinstance(data.get("user"), dict)
            else data
        )
        return {"success": True, "data": {"user": user, "market_base_url": self.base_url()}}
