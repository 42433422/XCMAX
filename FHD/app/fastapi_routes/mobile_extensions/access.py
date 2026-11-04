"""MobileAccess: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.mobile_extensions.protocols import (
    AuthHeaderCall,
    LatestMarketTokenCall,
    MobileSessionIdFromRequestCall,
    SessionMarketTokenCall,
    VerifyJwtCall,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MobileAccessPorts:
    verify_jwt: VerifyJwtCall
    mobile_session_id_from_request: MobileSessionIdFromRequestCall
    auth_header: AuthHeaderCall
    latest_market_token: LatestMarketTokenCall
    session_market_token: SessionMarketTokenCall


class MobileAccess:
    def __init__(self, ports: MobileAccessPorts) -> None:
        self.ports = ports

        def _mobile_session_id_from_request(request: Request) -> str:
            auth_raw = request.headers.get("Authorization") or ""
            auth_hdr = auth_raw if isinstance(auth_raw, str) else ""
            if auth_hdr.startswith("Bearer "):
                try:
                    payload = ports.verify_jwt(auth_hdr[7:].strip()) or {}
                    sid = str(payload.get("session_id") or "").strip()
                    if sid:
                        return sid
                except RECOVERABLE_ERRORS:
                    logger.exception("mobile session id parse failed")
            sid_raw = request.headers.get("X-Session-ID") or ""
            return sid_raw.strip() if isinstance(sid_raw, str) else ""

        self._mobile_session_id_from_request = _mobile_session_id_from_request

        def _mobile_market_authorization(request: Request, user: object = None) -> str:
            sid = ports.mobile_session_id_from_request(request)
            token = ports.session_market_token(sid) if sid else ""
            if not token:
                token = ports.latest_market_token(user_id=getattr(user, "id", None))
            return ports.auth_header(token)

        self._mobile_market_authorization = _mobile_market_authorization

        def _mobile_unauthorized_response() -> JSONResponse:
            return JSONResponse(
                format_mobile_response(None, "未授权", success=False, code=401), status_code=401
            )

        self._mobile_unauthorized_response = _mobile_unauthorized_response

        def _pairing_rate_allowed(key: str, endpoint: str, limit: int, window: int) -> bool:
            from app.utils.resilience.rate_limiter import (
                RateLimitBackendError,
                check_rate_limit,
                ensure_rate_limit_backend,
            )

            try:
                ensure_rate_limit_backend()
                return bool(check_rate_limit(key, endpoint, limit, window)["allowed"])
            except RateLimitBackendError:
                return False

        self._pairing_rate_allowed = _pairing_rate_allowed

        def _ai_circle_user(user: object) -> tuple[int, str, str | None]:
            uid = int(getattr(user, "id", 0) or 0)
            name = str(
                getattr(user, "display_name", "") or getattr(user, "username", "") or "企业成员"
            ).strip()
            avatar = getattr(user, "wx_avatar_url", None)
            return (uid, name, str(avatar).strip() if avatar else None)

        self._ai_circle_user = _ai_circle_user
