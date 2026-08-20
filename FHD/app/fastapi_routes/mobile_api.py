"""XCAGI Android 原生客户端 API（/api/mobile/v1）。"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_auth_support import (
    MobileLoginRequest,
    MobileRefreshRequest,
    MobileRegisterRequest,
    mobile_auth_success_payload,
    validate_mobile_session,
)
from app.fastapi_routes.mobile_auth_support import (
    bind_mobile_user_tenant_to_request as _bind_mobile_user_tenant_to_request,
)
from app.fastapi_routes.mobile_auth_support import (
    mobile_user_from_jwt_payload as _mobile_user_from_jwt_payload,
)
from app.fastapi_routes.mobile_auth_support import (
    parse_web_auth_login_response as _parse_web_auth_login_response,
)
from app.fastapi_routes.mobile_auth_support import (
    should_retry_mobile_admin_login as _should_retry_mobile_admin_login,
)
from app.fastapi_routes.mobile_auth_support import (
    user_public_dict as _user_public_dict,
)
from app.fastapi_routes.mobile_auth_support import (
    web_login_error_message as _web_login_error_message,
)
from app.security.mobile_jwt import (
    issue_mobile_tokens,
    refresh_mobile_access_token,
    user_id_from_mobile_bearer,
    verify_mobile_jwt,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobile/v1", tags=["mobile-api"])


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
        fallback_user = _mobile_user_from_jwt_payload(jwt_payload or {})
        if fallback_user is not None:
            _bind_mobile_user_tenant_to_request(request, fallback_user)
            return fallback_user
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
                        getattr(user, "tenant_id", None),
                        getattr(user, "wx_avatar_url", None),
                    )
                    if hasattr(db, "expunge"):
                        db.expunge(user)
                    _bind_mobile_user_tenant_to_request(request, user)
                    return user
        except RECOVERABLE_ERRORS as exc:
            logger.warning("mobile user db lookup failed, falling back to JWT: %s", exc)
        fallback_user = _mobile_user_from_jwt_payload(jwt_payload or {})
        _bind_mobile_user_tenant_to_request(request, fallback_user)
        return fallback_user

    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    _bind_mobile_user_tenant_to_request(request, user)
    return user


def _mobile_auth_success_payload(
    payload: dict[str, Any],
    *,
    account_kind: str,
    fallback_username: str,
) -> dict[str, Any] | None:
    return mobile_auth_success_payload(
        payload,
        account_kind=account_kind,
        fallback_username=fallback_username,
        issue_tokens=issue_mobile_tokens,
    )


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
    if payload.get("registered") and not payload.get("desktop_access"):
        return format_mobile_response(
            data={
                "registered": True,
                "authenticated": False,
                "account_state": payload.get("account_state") or "pending_plan",
                "next_action": payload.get("next_action") or "select_plan",
                "desktop_access": False,
                "purchase_url": payload.get("purchase_url"),
            },
            message="注册成功，请选择套餐并完成支付",
        )
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
    return await validate_mobile_session(
        request,
        user,
        verify_jwt=verify_mobile_jwt,
        public_user=_user_public_dict,
        logger=logger,
    )


@router.get("/host/discover-hint")
async def mobile_host_discover_hint(request: Request):
    from app.fastapi_routes.lan_routes import host_info
    from app.utils.device_system.listen_port import resolve_listen_port

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
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001  # pragma: no cover - production schema drift guard
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
