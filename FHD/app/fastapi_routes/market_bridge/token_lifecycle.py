"""One access-token validation state machine with explicit fast-probe policy."""

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from logging import Logger
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.application.market_bridge.protocols import LatestToken, ProxyJSON, SaveToken
from app.utils.operational_errors import RECOVERABLE_ERRORS

# A successful fast probe is enough for the next navigation. Repeating the
# market round-trip on every reload is what keeps the desktop splash up.
_FAST_OK_TTL_S = 45.0
_fast_ok_until: dict[tuple[str, int, str], tuple[str, float]] = {}
_FAST_OK_MAX_ENTRIES = 1024


def invalidate_fast_token_validation(session_id: str) -> None:
    for key in list(_fast_ok_until):
        if key[0] == (session_id or "").strip():
            _fast_ok_until.pop(key, None)


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
    validation_origin: Callable[[], str]
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

    async def probe(self, session_id: str, clear: Callable[[str], None]) -> str:
        """Apply a definitive rejection only to the credentials actually probed."""

        def identity() -> tuple[str, str, int | None]:
            return (
                self.access_token(session_id),
                self.refresh_token(session_id),
                self.user_id(session_id),
            )

        before = identity()

        def save(session_id: str, token: str, refresh_token: str | None = None) -> None:
            if identity() == before:
                self.save(session_id, token, refresh_token)

        guarded = replace(self, save=save)

        async def refresh(sid: str) -> str:
            if identity() != before:
                return self.access_token(sid)
            return await guarded.refresh(sid, distinguish_errors=True)

        guarded.refresh_session = refresh
        try:
            token = await guarded.resolve(session_id, fast=True, allow_latest=False)
        except HTTPException as exc:
            if exc.status_code == 403:
                token = ""
            else:
                self.logger.warning("market session probe deferred: refresh unavailable")
                return self.access_token(session_id)
        except RECOVERABLE_ERRORS:
            self.logger.warning("market session probe deferred: transport unavailable")
            return self.access_token(session_id)
        if not token and identity() == before:
            invalidate_fast_token_validation(session_id)
            clear(session_id)
        return token if identity() == before else self.access_token(session_id)

    async def resolve(
        self, session_id: str, *, fast: bool = False, allow_latest: bool = True
    ) -> str:
        sid = (session_id or "").strip()
        owner = self.user_id(sid)
        token = self.normalize(self.access_token(sid))
        if allow_latest and not token and owner is not None:
            token = self.normalize(self.latest_token(user_id=owner))
        if not token or self.is_demo(token):
            invalidate_fast_token_validation(sid)
            return token
        cache_key = (sid, owner, self.validation_origin()) if sid and owner is not None else None
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        if fast and cache_key is not None:
            cached = _fast_ok_until.get(cache_key)
            if cached and cached[0] == token_digest and cached[1] > time.monotonic():
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
            if response.status_code == 401:
                invalidate_fast_token_validation(sid)
                return self.normalize(await self.refresh_session(sid))
            if not fast:
                self.logger.warning(
                    "market unreachable during token validation (session_id=%s), using local token",
                    sid[:8],
                )
            return token
        if isinstance(response, dict) and response.get("__proxy_error__"):
            if self.proxy_status(response) == 401:
                invalidate_fast_token_validation(sid)
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
            if fast:
                return token
            invalidate_fast_token_validation(sid)
            return self.normalize(await self.refresh_session(sid))
        if (
            fast
            and cache_key is not None
            and isinstance(response, dict)
            and (
                isinstance(response.get("user"), dict)
                or response.get("ok") is True
                or response.get("success") is True
            )
        ):
            now = time.monotonic()
            for key, (_, expires) in list(_fast_ok_until.items()):
                if expires <= now:
                    _fast_ok_until.pop(key, None)
            if len(_fast_ok_until) >= _FAST_OK_MAX_ENTRIES:
                _fast_ok_until.pop(next(iter(_fast_ok_until)))
            _fast_ok_until[cache_key] = (token_digest, now + _FAST_OK_TTL_S)
        return token
