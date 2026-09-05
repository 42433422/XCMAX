"""Issue browser login codes for the authenticated FHD session only."""

import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.auth.dependencies import resolve_session_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter()


class BrowserHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(max_length=1024)
    purpose: Literal["wallet", "plans"]


async def _market_browser_handoff(body: BrowserHandoffRequest, request: Request):
    from app.fastapi_routes import market_account as market

    user = resolve_session_user(request)
    sid = market.session_id_from_request(request)
    if (
        user is None
        or getattr(user, "id", None) is None
        or not getattr(user, "is_active", True)
        or not sid
        or market._user_id_from_session(sid) != user.id
    ):
        raise HTTPException(401, "请先登录桌面账号")
    parts = urlsplit(body.target)
    if (
        parts.scheme
        or parts.netloc
        or parts.fragment
        or "\\" in body.target
        or parts.path != {"wallet": "/wallet", "plans": "/plans"}[body.purpose]
    ):
        raise HTTPException(400, "不支持此登录目标")
    # Do not use the global latest-session fallback or caller-supplied tokens.
    token = market._normalize_bearer_token(market.session_market_token(sid))
    if not token:
        raise HTTPException(401, "请重新登录以连接市场账号")
    payload = await market._proxy_json(
        "POST",
        "/api/auth/browser-handoff",
        json_body={"target": body.target, "purpose": body.purpose},
        authorization=f"Bearer {token}",
        return_error_payload=True,
        sensitive=True,
    )
    if (
        isinstance(payload, dict)
        and payload.get("__proxy_error__")
        and payload.get("status_code") == 401
    ):
        refresh = market.session_market_refresh_token(sid)
        if refresh:
            renewed = await market._proxy_json(
                "POST",
                "/api/auth/refresh",
                json_body={"refresh_token": refresh},
                return_error_payload=True,
                sensitive=True,
            )
            if isinstance(renewed, dict) and not renewed.get("__proxy_error__"):
                access = market._token_from_auth_response(renewed)
                if access:
                    market.save_session_market_token(
                        sid, access, market._refresh_token_from_auth_response(renewed) or refresh
                    )
                    payload = await market._proxy_json(
                        "POST",
                        "/api/auth/browser-handoff",
                        json_body={"target": body.target, "purpose": body.purpose},
                        authorization=f"Bearer {access}",
                        return_error_payload=True,
                        sensitive=True,
                    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not re.fullmatch(
        r"[A-Za-z0-9_-]{43}", str(data.get("code") or "")
    ):
        # Never forward remote response bodies: they can include authentication context.
        status = 401 if isinstance(payload, dict) and payload.get("status_code") == 401 else 503
        raise HTTPException(status, "暂时无法连接市场账号，请重试或重新登录")
    return JSONResponse(
        {
            "success": True,
            "data": {key: data.get(key) for key in ("code", "target", "purpose", "expires_in")},
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/browser-handoff")
async def market_browser_handoff(body: BrowserHandoffRequest, request: Request):
    try:
        return await _market_browser_handoff(body, request)
    except HTTPException as exc:
        exc.headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
        raise
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(
            503, "市场会话暂时不可用，请重试", headers={"Cache-Control": "no-store"}
        ) from exc
