"""XCAGI Android 原生客户端 API（/api/mobile/v1）。"""

from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.security.mobile_jwt import (
    issue_mobile_tokens,
    refresh_mobile_access_token,
    user_id_from_mobile_bearer,
    verify_mobile_jwt,
)
from app.utils.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobile/v1", tags=["mobile-api"])


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


def _user_public_dict(user) -> dict[str, Any]:
    from app.utils.user_avatar_storage import public_avatar_url

    return {
        "id": int(getattr(user, "id", 0) or 0),
        "username": str(getattr(user, "username", "") or ""),
        "display_name": str(getattr(user, "display_name", "") or ""),
        "email": str(getattr(user, "email", "") or ""),
        "role": str(getattr(user, "role", "") or ""),
        "is_active": bool(getattr(user, "is_active", True)),
        "avatar_url": public_avatar_url(getattr(user, "wx_avatar_url", None)),
    }


def _mobile_user_from_jwt_payload(payload: dict[str, Any]) -> Any | None:
    """云端签发的移动 JWT 作为身份载体（本地 users 行缺失/过期时的收敛路径）。

    身份真相源契约见 docs/account_system_ssot.md §9.2：移动 JWT 由本端在**市场认证
    通过后**签发（``aud=xcagi-mobile``），携带的是云端已确认的身份。当本地 ``users``
    表滞后于云端时，信任已验签的 JWT 是**设计而非漏洞**——本地行只是缓存。

    该重建路径**仅限**两类：管理端（``account_kind ∈ {admin, admin_portal}``）或物理
    中继会话（``session_id`` 以 ``mobile-relay-`` 开头）。每次走该路径打 WARNING 日志
    （§零「云端为准」要求的可观测降级）。受控点由 account-identity 守卫冻结，禁止外扩。
    """
    if not payload or payload.get("typ") != "access":
        return None
    uid = int(payload.get("user_id") or 0)
    if uid <= 0:
        return None
    account_kind = str(payload.get("account_kind") or "").strip().lower()
    session_id = str(payload.get("session_id") or "").strip()
    if account_kind not in {"admin", "admin_portal"} and not session_id.startswith("mobile-relay-"):
        return None
    username = str(payload.get("username") or "").strip() or "mobile"
    role = "admin" if account_kind in {"admin", "admin_portal"} else "enterprise"
    logger.warning(
        "mobile identity rebuilt from signed JWT (cloud-authority degraded path): "
        "uid=%s account_kind=%s session=%s",
        uid,
        account_kind or "-",
        session_id or "-",
    )
    return SimpleNamespace(
        id=uid,
        username=username,
        display_name=username,
        email="",
        role=role,
        is_active=True,
        wx_avatar_url=None,
    )


async def get_mobile_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    """Bearer 移动端 JWT 或会话 Cookie / X-Session-ID。"""
    from app.db.models import User
    from app.db.session import get_db

    authorization_value = authorization or ""
    jwt_payload = None
    if authorization_value.startswith("Bearer "):
        jwt_payload = verify_mobile_jwt(authorization_value[7:].strip())
    uid = user_id_from_mobile_bearer(authorization_value)
    if uid is None and authorization_value.startswith("Bearer "):
        return None
    if uid is not None:
        try:
            with get_db() as db:
                user = db.query(User).filter(User.id == uid).first()
                if user and user.is_active:
                    jwt_account_kind = (
                        str((jwt_payload or {}).get("account_kind") or "").strip().lower()
                    )
                    jwt_admin = jwt_account_kind in {"admin", "admin_portal"}
                    user_role = str(getattr(user, "role", "") or "").strip()
                    if jwt_admin and user_role not in {"admin", "super_admin", "owner"}:
                        fallback = _mobile_user_from_jwt_payload(jwt_payload or {})
                        if fallback is not None:
                            return fallback
                    _ = (
                        user.id,
                        user.username,
                        user.display_name,
                        user.email,
                        user.role,
                        user.is_active,
                        getattr(user, "wx_avatar_url", None),
                    )
                    if hasattr(db, "expunge"):
                        db.expunge(user)
                    return user
        except RECOVERABLE_ERRORS as exc:
            logger.warning("mobile user db lookup failed, falling back to JWT: %s", exc)
        return _mobile_user_from_jwt_payload(jwt_payload or {})

    from app.infrastructure.auth.dependencies import resolve_session_user

    return resolve_session_user(request)


def _parse_web_auth_login_response(web_resp: Any) -> tuple[dict[str, Any], int]:
    """解析 ``POST /api/auth/login`` 的 JSONResponse（与 Web 桌面端同源）。"""
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


def _web_login_error_message(payload: dict[str, Any]) -> str:
    err = payload.get("error")
    if isinstance(err, dict):
        msg = str(err.get("message") or "").strip()
        if msg:
            return msg
    return str(payload.get("message") or "登录失败").strip() or "登录失败"


def _should_retry_mobile_admin_login(message: str, account_kind: str) -> bool:
    if account_kind.strip().lower() in {"admin", "admin_portal"}:
        return False
    return "管理员账号不能从企业账号入口登录" in message or "管理员入口登录" in message


def _mobile_auth_success_payload(
    payload: dict[str, Any],
    *,
    account_kind: str,
    fallback_username: str,
) -> dict[str, Any] | None:
    session_id = str(payload.get("session_id") or "").strip()
    user_raw = payload.get("user")
    if not session_id or not isinstance(user_raw, dict) or user_raw.get("id") is None:
        return None
    resolved_kind = str(payload.get("account_kind") or account_kind).strip() or account_kind
    username = str(user_raw.get("username") or fallback_username).strip()
    tokens = issue_mobile_tokens(
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
    for key in (
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
    ):
        if key in payload and payload[key] is not None:
            data[key] = payload[key]
    return data


def _mobile_auth_error_response(
    payload: dict[str, Any],
    status: int,
    *,
    fallback_message: str,
) -> JSONResponse:
    message = _web_login_error_message(payload)
    if not message or message == "登录失败":
        message = str(payload.get("message") or fallback_message).strip() or fallback_message
    code = status if status >= 400 else 401
    return JSONResponse(
        format_mobile_response(
            data={"error": message, "error_id": payload.get("error_id")},
            message=message,
            success=False,
            code=code,
        ),
        status_code=code,
    )


@router.post("/auth/register", response_model=dict[str, Any])
async def mobile_auth_register(body: MobileRegisterRequest):
    """移动端注册：复用桌面 ``/api/auth/register``，成功后直接签发 mobile JWT。"""
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.domains.auth.routes import auth_register
    from app.mod_sdk.product_skus import resolve_product_sku

    sku = resolve_product_sku()
    default_kind = "enterprise" if sku == "enterprise" else "personal"
    account_kind = normalize_account_kind(body.account_kind, default=default_kind)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/register",
        "headers": [],
    }
    request = Request(scope)
    web_resp = await auth_register(
        request,
        {
            "username": body.username.strip(),
            "password": body.password,
            "email": body.email.strip(),
            "verification_code": body.verification_code.strip(),
            "industry_id": body.industry_id.strip(),
            "budget_range": body.budget_range.strip(),
            "account_kind": account_kind,
        },
    )
    payload, status = _parse_web_auth_login_response(web_resp)
    if not payload.get("success"):
        return _mobile_auth_error_response(payload, status, fallback_message="注册失败")
    data = _mobile_auth_success_payload(
        payload,
        account_kind=account_kind,
        fallback_username=body.username.strip(),
    )
    if data is None:
        return JSONResponse(
            format_mobile_response(data=None, message="会话创建失败", success=False, code=500),
            status_code=500,
        )
    return format_mobile_response(data=data, message="注册成功")


@router.post("/auth/login")
async def mobile_auth_login(body: MobileLoginRequest):
    """与 Web ``POST /api/auth/login`` 共用认证逻辑（市场校验、JIT、account_kind、市场 token）。"""
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.domains.auth.routes import auth_login
    from app.mod_sdk.product_skus import resolve_product_sku

    sku = resolve_product_sku()
    default_kind = "enterprise" if sku == "enterprise" else "personal"
    account_kind = normalize_account_kind(body.account_kind, default=default_kind)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": [],
    }
    request = Request(scope)
    web_resp = await auth_login(
        request,
        {
            "username": body.username.strip(),
            "password": body.password,
            "account_kind": account_kind,
        },
    )
    payload, status = _parse_web_auth_login_response(web_resp)
    if not payload.get("success"):
        message = _web_login_error_message(payload)
        if _should_retry_mobile_admin_login(message, account_kind):
            web_resp = await auth_login(
                request,
                {
                    "username": body.username.strip(),
                    "password": body.password,
                    "account_kind": "admin",
                },
            )
            payload, status = _parse_web_auth_login_response(web_resp)
            account_kind = "admin"
            if payload.get("success"):
                message = ""
            else:
                message = _web_login_error_message(payload)
        if not payload.get("success"):
            code = status if status >= 400 else 401
            return JSONResponse(
                format_mobile_response(
                    data={"error": message, "error_id": payload.get("error_id")},
                    message=message,
                    success=False,
                    code=code,
                ),
                status_code=code,
            )

    data = _mobile_auth_success_payload(
        payload,
        account_kind=account_kind,
        fallback_username=body.username.strip(),
    )
    if data is None:
        return JSONResponse(
            format_mobile_response(
                data=None,
                message="会话创建失败",
                success=False,
                code=500,
            ),
            status_code=500,
        )
    return format_mobile_response(data=data, message="登录成功")


@router.post("/auth/login-with-phone-code")
async def mobile_auth_login_with_phone(body: dict):
    """与 Web ``POST /api/auth/login-with-phone-code`` 共用逻辑。"""
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.domains.auth.routes import auth_login_with_phone_code
    from app.mod_sdk.product_skus import resolve_product_sku

    sku = resolve_product_sku()
    default_kind = "enterprise" if sku == "enterprise" else "personal"
    phone = str(body.get("phone") or "").strip()
    code = str(body.get("code") or "").strip()
    account_kind = normalize_account_kind(body.get("account_kind"), default=default_kind)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login-with-phone-code",
        "headers": [],
    }
    request = Request(scope)
    web_resp = await auth_login_with_phone_code(
        request,
        {
            "phone": phone,
            "code": code,
            "account_kind": account_kind,
            "username": body.get("username"),
        },
    )
    payload, status = _parse_web_auth_login_response(web_resp)
    if not payload.get("success"):
        message = _web_login_error_message(payload)
        code_out = status if status >= 400 else 401
        return JSONResponse(
            format_mobile_response(
                data={"error": message}, message=message, success=False, code=code_out
            ),
            status_code=code_out,
        )
    data = _mobile_auth_success_payload(
        payload,
        account_kind=account_kind,
        fallback_username=phone,
    )
    if data is None:
        return JSONResponse(
            format_mobile_response(data=None, message="会话创建失败", success=False, code=500),
            status_code=500,
        )
    return format_mobile_response(data=data, message="登录成功")


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


@router.get("/auth/session/validate", response_model=dict[str, Any])
async def mobile_auth_session_validate(request: Request, user=Depends(get_mobile_user)):
    """移动端冷启动会话校验：校验 mobile JWT 绑定的 FHD session 并刷新权益。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(
                data={"valid": False},
                message="未授权",
                success=False,
                code=401,
            ),
            status_code=401,
        )
    auth_hdr = request.headers.get("Authorization") or ""
    payload = verify_mobile_jwt(auth_hdr[7:].strip()) if auth_hdr.startswith("Bearer ") else None
    session_id = str((payload or {}).get("session_id") or request.headers.get("X-Session-ID") or "").strip()
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
        "user": _user_public_dict(user),
        "session": session_info,
        "account_kind": meta.get("account_kind") or (payload or {}).get("account_kind") or "enterprise",
        "company_brand": meta.get("company_brand"),
        "entitled_mod_ids": entitled_mod_ids,
    }
    if market_token:
        data["market_access_token"] = market_token
    if market_refresh:
        data["market_refresh_token"] = market_refresh
    return format_mobile_response(data=data, message="会话有效")


@router.get("/host/discover-hint")
async def mobile_host_discover_hint(request: Request):
    from app.fastapi_routes.lan_routes import host_info
    from app.utils.listen_port import resolve_listen_port

    info = await host_info(request)
    instance_name = os.environ.get("SERVICE_BRIDGE_INSTANCE_NAME", "XCAGI 宿主")
    return format_mobile_response(
        data={
            "lan": info.model_dump(),
            "instance_name": instance_name,
            "api_port": resolve_listen_port(),
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
    try:
        permissions = auth_app.get_user_permissions(user)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - production schema drift guard
        logger.warning("mobile me permissions fallback: %s", exc)
        role = str(getattr(user, "role", "") or "").strip()
        permissions = ["*"] if role in {"admin", "super_admin", "owner"} else []
    sid = ""
    jwt_meta: dict[str, Any] = {}
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.startswith("Bearer "):
        payload = verify_mobile_jwt(auth_hdr[7:].strip())
        if payload:
            sid = str(payload.get("session_id") or "")
            account_kind = str(payload.get("account_kind") or "").strip()
            if account_kind:
                jwt_meta["account_kind"] = account_kind
    if not sid:
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
    meta = (load_session_account_meta(sid) if sid else {}) or jwt_meta

    mods_summary: list[dict[str, str]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        for entry in (mgr.list_mods() or [])[:50]:
            mid = str(entry.get("id") or entry.get("mod_id") or "")
            if mid:
                mods_summary.append({"id": mid})
    except RECOVERABLE_ERRORS as exc:
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
