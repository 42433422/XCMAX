"""XCAGI Android 原生客户端 API（/api/mobile/v1）。"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.security.mobile_jwt import (
    issue_mobile_tokens,
    refresh_mobile_access_token,
    user_id_from_mobile_bearer,
    verify_mobile_jwt,
)
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobile/v1", tags=["mobile-api"])


class MobileLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)
    account_kind: str = Field(default="enterprise", max_length=32)


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


def _user_public_dict(user) -> dict[str, Any]:
    from app.utils.user_avatar_storage import public_avatar_url

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "avatar_url": public_avatar_url(getattr(user, "wx_avatar_url", None)),
    }


async def get_mobile_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    """Bearer 移动端 JWT 或会话 Cookie / X-Session-ID。"""
    from app.db.models import User
    from app.db.session import get_db

    uid = user_id_from_mobile_bearer(authorization)
    if uid is not None:
        with get_db() as db:
            user = db.query(User).filter(User.id == uid).first()
            if user and user.is_active:
                return user
        return None

    from app.fastapi_routes.legacy_helpers import _require_login_user

    user, err = _require_login_user(request)
    if err:
        return None
    return user


@router.post("/auth/login")
async def mobile_auth_login(body: MobileLoginRequest):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.session_account_meta import normalize_account_kind, persist_session_account_meta

    auth = get_auth_app_service()
    result = auth.login(body.username.strip(), body.password)
    if not result.get("success"):
        return JSONResponse(
            format_mobile_response(
                data={"error": result.get("message", "登录失败")},
                message=str(result.get("message") or "登录失败"),
                success=False,
                code=401,
            ),
            status_code=401,
        )

    session_id = str(result.get("session_id") or "")
    user = result.get("user")
    if not user or not session_id:
        return JSONResponse(
            format_mobile_response(
                data=None,
                message="会话创建失败",
                success=False,
                code=500,
            ),
            status_code=500,
        )

    account_kind = normalize_account_kind(body.account_kind, default="enterprise")
    try:
        persist_session_account_meta(
            session_id,
            account_kind=account_kind,
            company_brand="成都修茈科技有限公司",
        )
    except Exception as exc:
        logger.warning("mobile login session meta: %s", exc)

    tokens = issue_mobile_tokens(
        user_id=int(user.id),
        session_id=session_id,
        account_kind=account_kind,
        username=str(user.username or ""),
    )
    return format_mobile_response(
        data={
            "user": _user_public_dict(user),
            "session_id": session_id,
            "account_kind": account_kind,
            **tokens,
            "expires_in": 24 * 3600,
        },
        message="登录成功",
    )


@router.post("/auth/refresh")
async def mobile_auth_refresh(body: MobileRefreshRequest):
    tokens = refresh_mobile_access_token(body.refresh_token.strip())
    if not tokens:
        return JSONResponse(
            format_mobile_response(
                data=None,
                message="refresh_token 无效或已过期",
                success=False,
                code=401,
            ),
            status_code=401,
        )
    return format_mobile_response(data={**tokens, "expires_in": 24 * 3600})


@router.get("/host/discover-hint")
async def mobile_host_discover_hint(request: Request):
    from app.fastapi_routes.lan_routes import host_info

    info = await host_info(request)
    instance_name = os.environ.get("SERVICE_BRIDGE_INSTANCE_NAME", "XCAGI 宿主")
    return format_mobile_response(
        data={
            "lan": info.model_dump(),
            "instance_name": instance_name,
            "api_port": int(os.environ.get("PORT", "5000") or 5000),
            "company": "成都修茈科技有限公司",
            "brand_url": "https://xiu-ci.com",
        },
    )


@router.get("/me")
async def mobile_me(request: Request, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(
                data=None,
                message="未授权",
                success=False,
                code=401,
            ),
            status_code=401,
        )

    from app.application.auth_app_service import get_auth_app_service
    from app.application.session_account_meta import load_session_account_meta
    auth_app = get_auth_app_service()
    permissions = auth_app.get_user_permissions(user)
    sid = ""
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.startswith("Bearer "):
        payload = verify_mobile_jwt(auth_hdr[7:].strip())
        if payload:
            sid = str(payload.get("session_id") or "")
    if not sid:
        from app.fastapi_routes.legacy_helpers import _session_id_from_request

        sid = _session_id_from_request(request)
    meta = load_session_account_meta(sid) if sid else {}

    mods_summary: list[dict[str, str]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        for entry in (mgr.list_mods() or [])[:50]:
            mid = str(entry.get("id") or entry.get("mod_id") or "")
            if mid:
                mods_summary.append({"id": mid})
    except Exception as exc:
        logger.debug("mods list for mobile me: %s", exc)

    return format_mobile_response(
        data={
            "user": _user_public_dict(user),
            "permissions": permissions,
            "account_kind": meta.get("account_kind") or "enterprise",
            "company_brand": meta.get("company_brand") or "成都修茈科技有限公司",
            "mods": mods_summary,
        },
    )


@router.get("/health")
async def mobile_health():
    return format_mobile_response(
        data={"service": "xcagi-mobile", "status": "ok"},
    )


from app.fastapi_routes.mobile_api_extensions import extension_router  # noqa: E402

router.include_router(extension_router)
