"""Shared models and helpers for the mobile authentication routes."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS


class MobileLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)
    account_kind: str = Field(default="enterprise", max_length=32)


class MobileRegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)
    email: str = Field(default="", max_length=256)
    verification_code: str = Field(default="", max_length=32)
    industry_id: str = Field(default="通用", max_length=64)
    budget_range: str = Field(default="", max_length=64)
    account_kind: str = Field(default="enterprise", max_length=32)


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


def user_public_dict(user: Any) -> dict[str, Any]:
    from app.utils.no_email import email_display, is_no_email_address
    from app.utils.path_io.user_avatar_storage import public_avatar_url

    raw_email = str(getattr(user, "email", "") or "")
    return {
        "id": int(getattr(user, "id", 0) or 0),
        "username": str(getattr(user, "username", "") or ""),
        "display_name": str(getattr(user, "display_name", "") or ""),
        "email": raw_email,
        "email_display": email_display(raw_email),
        "no_email": is_no_email_address(raw_email),
        "role": str(getattr(user, "role", "") or ""),
        "is_active": bool(getattr(user, "is_active", True)),
        "avatar_url": public_avatar_url(getattr(user, "wx_avatar_url", None)),
        "tenant_id": getattr(user, "tenant_id", None),
    }


def mobile_user_from_jwt_payload(payload: dict[str, Any]) -> Any | None:
    """Build a relay/admin fallback user when the local user row is stale."""
    if not payload or payload.get("typ") not in (None, "access"):
        return None
    uid = int(payload.get("user_id") or 0)
    account_kind = str(payload.get("account_kind") or "").strip().lower()
    session_id = str(payload.get("session_id") or "").strip()
    is_relay = session_id.startswith("mobile-relay-")
    if uid <= 0 and not is_relay:
        return None
    if account_kind not in {"admin", "admin_portal"} and not is_relay:
        return None
    username = str(payload.get("username") or "").strip() or "mobile"
    role = "admin" if account_kind in {"admin", "admin_portal"} else "enterprise"
    return SimpleNamespace(
        id=uid if uid > 0 else 0,
        username=username,
        display_name=username,
        email="",
        role=role,
        is_active=True,
        wx_avatar_url=None,
        tenant_id=payload.get("tenant_id"),
    )


def bind_mobile_user_tenant_to_request(request: Request, user: Any | None) -> None:
    if user is None:
        return
    try:
        tenant_id = getattr(user, "tenant_id", None)
        request.state.tenant_id = int(tenant_id) if tenant_id is not None else None
    except (TypeError, ValueError, AttributeError):
        request.state.tenant_id = None


def parse_web_auth_login_response(web_resp: Any) -> tuple[dict[str, Any], int]:
    """Parse the JSONResponse returned by the shared web authentication routes."""
    status = int(getattr(web_resp, "status_code", 200) or 200)
    if isinstance(web_resp, JSONResponse):
        raw = web_resp.body
        if not raw:
            return {"success": False, "message": "登录失败"}, status
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8")), status
        return json.loads(str(raw)), status
    if isinstance(web_resp, dict):
        return web_resp, status
    return {"success": False, "message": "登录失败"}, status


def web_login_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    return str(payload.get("message") or "登录失败").strip() or "登录失败"


def should_retry_mobile_admin_login(message: str, account_kind: str) -> bool:
    if account_kind.strip().lower() in {"admin", "admin_portal"}:
        return False
    return "管理员账号不能从企业账号入口登录" in message or "管理员入口登录" in message


def mobile_auth_success_payload(
    payload: dict[str, Any],
    *,
    account_kind: str,
    fallback_username: str,
    issue_tokens: Callable[..., dict[str, str]],
) -> dict[str, Any] | None:
    session_id = str(payload.get("session_id") or "").strip()
    user_raw = payload.get("user")
    if not session_id or not isinstance(user_raw, dict) or user_raw.get("id") is None:
        return None
    resolved_kind = str(payload.get("account_kind") or account_kind).strip() or account_kind
    username = str(user_raw.get("username") or fallback_username).strip()
    tokens = issue_tokens(
        user_id=int(user_raw["id"]),
        session_id=session_id,
        account_kind=resolved_kind,
        username=username,
    )
    data: dict[str, Any] = {
        "user": user_raw,
        "session_id": session_id,
        "account_kind": resolved_kind,
        **tokens,
        "expires_in": 24 * 3600,
    }
    passthrough_keys = (
        "market_access_token",
        "market_refresh_token",
        "company_brand",
        "tenant_id",
        "tenant_name",
        "market_is_admin",
        "market_is_enterprise",
        "entitled_mod_ids",
        "tier",
        "account_tier",
        "budget_range",
        "industry_id",
        "entitled_industries",
        "market_membership_tier",
    )
    for key in passthrough_keys:
        if key in payload and payload[key] is not None:
            data[key] = payload[key]
    return data


async def validate_mobile_session(
    request: Request,
    user: Any,
    *,
    verify_jwt: Callable[[str], dict[str, Any] | None],
    public_user: Callable[[Any], dict[str, Any]],
    logger: logging.Logger,
) -> dict[str, Any] | JSONResponse:
    """Validate an FHD or relay session and refresh its market entitlements."""
    if user is None:
        return JSONResponse(
            format_mobile_response(
                data={"valid": False}, message="未授权", success=False, code=401
            ),
            status_code=401,
        )
    auth_header = request.headers.get("Authorization") or ""
    payload = verify_jwt(auth_header[7:].strip()) if auth_header.startswith("Bearer ") else None
    session_id = str(
        (payload or {}).get("session_id") or request.headers.get("X-Session-ID") or ""
    ).strip()
    if not session_id:
        return JSONResponse(
            format_mobile_response(
                data={"valid": False},
                message="会话缺少 session_id",
                success=False,
                code=401,
            ),
            status_code=401,
        )

    from app.application.auth_app_service import get_auth_app_service
    from app.application.session_account_meta import load_session_account_meta

    auth_app_service = get_auth_app_service()
    if session_id.startswith("mobile-relay-"):
        meta = load_session_account_meta(session_id) or {}
        relay_data: dict[str, Any] = {
            "valid": True,
            "session_id": session_id,
            "user": public_user(user),
            "session": {"session_id": session_id, "relay": True},
            "account_kind": meta.get("account_kind")
            or (payload or {}).get("account_kind")
            or "enterprise",
            "company_brand": meta.get("company_brand"),
            "entitled_mod_ids": [],
        }
        return format_mobile_response(data=relay_data, message="会话有效")

    session_info = auth_app_service.session_manager.get_session_info(session_id)
    if not session_info:
        return JSONResponse(
            format_mobile_response(
                data={"valid": False},
                message="会话无效或已过期",
                success=False,
                code=401,
            ),
            status_code=401,
        )
    entitled_mod_ids: list[str] = []
    try:
        from app.enterprise.mod_entitlements import sync_entitlements_for_session

        entitled = await sync_entitlements_for_session(session_id)
        if entitled:
            entitled_mod_ids = sorted(entitled)
    except RECOVERABLE_ERRORS:
        logger.exception("mobile session validate entitlement sync failed")
    market_token = ""
    market_refresh = ""
    try:
        from app.fastapi_routes.market_account import (
            resolve_valid_market_access_token,
            session_market_refresh_token,
        )

        market_token = await resolve_valid_market_access_token(session_id)
        market_refresh = session_market_refresh_token(session_id)
    except RECOVERABLE_ERRORS:
        logger.exception("mobile session validate market token refresh failed")
    meta = load_session_account_meta(session_id) or {}
    data: dict[str, Any] = {
        "valid": True,
        "session_id": session_id,
        "user": public_user(user),
        "session": session_info,
        "account_kind": meta.get("account_kind")
        or (payload or {}).get("account_kind")
        or "enterprise",
        "company_brand": meta.get("company_brand"),
        "entitled_mod_ids": entitled_mod_ids,
    }
    if market_token:
        data["market_access_token"] = market_token
    if market_refresh:
        data["market_refresh_token"] = market_refresh
    return format_mobile_response(data=data, message="会话有效")
