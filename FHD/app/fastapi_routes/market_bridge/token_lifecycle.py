"""One access-token validation state machine with explicit fast-probe policy."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import LatestToken, ProxyJSON, SaveToken


@dataclass
class TokenLifecycle:
    access_token: Callable[[str], str]
    refresh_token: Callable[[str], str]
    latest_token: LatestToken
    user_id: Callable[[str], int | None]
    normalize: Callable[[str], str]
    access_from_payload: Callable[[Any], str]
    refresh_from_payload: Callable[[Any], str]
    save: SaveToken
    proxy: ProxyJSON
    refresh_session: Callable[[str], Awaitable[str]]
    is_demo: Callable[[str], bool]
    proxy_status: Callable[[Any], int | None]
    fast_timeout: Callable[[], float]
    logger: Logger

    async def refresh(self, session_id: str, *, distinguish_errors: bool = False) -> str:
        sid = (session_id or "").strip()
        if not sid:
            return ""
        refresh = self.refresh_token(sid)
        if not refresh:
            return ""
        payload = await self.proxy(
            "POST",
            "/api/auth/refresh",
            json_body={"refresh_token": refresh},
            return_error_payload=True,
        )
        if isinstance(payload, JSONResponse) or (
            isinstance(payload, dict) and payload.get("__proxy_error__")
        ):
            status = (
                payload.status_code
                if isinstance(payload, JSONResponse)
                else int(payload.get("status_code") or 503)
            )
            if distinguish_errors and status != 401:
                raise HTTPException(
                    status_code=403 if status == 403 else 503,
                    detail="市场账号无权刷新登录"
                    if status == 403
                    else "市场登录服务暂时不可用，请稍后恢复；草稿未发送",
                )
            return ""
        access = self.access_from_payload(payload)
        if distinguish_errors and not access:
            raise HTTPException(status_code=503, detail="市场登录服务返回无效响应；草稿未发送")
        new_refresh = self.refresh_from_payload(payload) or refresh
        if access:
            self.save(sid, access, new_refresh)
        return access

    async def resolve(self, session_id: str, *, fast: bool = False) -> str:
        sid = (session_id or "").strip()
        owner = self.user_id(sid)
        token = self.normalize(self.access_token(sid))
        if not token and owner is not None:
            token = self.normalize(self.latest_token(user_id=owner))
        if not token or self.is_demo(token):
            return token
        try:
            if fast:
                # The proxy's legacy retries argument is an attempt budget.
                response = await self.proxy(
                    "GET",
                    "/api/auth/me",
                    authorization=f"Bearer {token}",
                    return_error_payload=True,
                    timeout=self.fast_timeout(),
                    retries=1,
                )
            else:
                response = await self.proxy(
                    "GET",
                    "/api/auth/me",
                    authorization=f"Bearer {token}",
                    return_error_payload=True,
                )
        except RECOVERABLE_ERRORS:
            if not fast:
                raise
            self.logger.warning(
                "market token fast-validate transport error (session_id=%s), fail-open to local token",
                sid[:8],
            )
            return token
        if isinstance(response, JSONResponse):
            if not fast:
                self.logger.warning(
                    "market unreachable during token validation (session_id=%s), using local token",
                    sid[:8],
                )
            return token
        if isinstance(response, dict) and response.get("__proxy_error__"):
            if self.proxy_status(response) == 401:
                return self.normalize(await self.refresh_session(sid))
            if not fast:
                self.logger.warning(
                    "market /api/auth/me error status=%s, using local token",
                    response.get("status_code"),
                )
            return token
        if isinstance(response, dict) and (
            response.get("ok") is False or response.get("success") is False
        ):
            return self.normalize(await self.refresh_session(sid))
        return token
