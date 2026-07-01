"""Migrated from legacy_auth.py (v10)."""

from __future__ import annotations

import logging
import os
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.http.error_codes import (
    ACCOUNT_DISABLED,
    CREATE_FAILED,
    INVALID_FILE,
    INVALID_INPUT,
    INVALID_ROLE,
    INVALID_SESSION,
    LOCAL_LOGIN_AFTER_REGISTER,
    LOGIN_AFTER_REGISTER,
    MARKET_NOT_BOUND,
    MARKET_REGISTER_FAILED,
    MARKET_RESET_FAILED,
    MISSING_PASSWORD,
    NO_SESSION,
    NOT_FOUND,
    QR_NOT_FOUND,
    REGISTRATION_DISABLED,
    SAVE_FAILED,
    SELF_DELETE,
    SEND_CODE_FAILED,
    UNAUTHORIZED,
    UPDATE_FAILED,
    WEAK_PASSWORD,
    error_envelope,
)
from app.infrastructure.auth.dependencies import (
    get_logged_in_user,
    require_permission,
    resolve_session_user,
    session_id_from_request,
)
from app.utils.operational_errors import INFRA_TRANSIENT

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-auth"], deprecated=True)

_require_admin = require_permission("admin.manage_users")


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


def _session_meta_for_response(request: Request, user=None) -> dict[str, Any]:
    from app.application.session_account_meta import (
        enrich_session_meta_with_tenant,
        load_session_account_meta,
    )

    sid = session_id_from_request(request)
    if not sid:
        return {}
    if user is not None:
        return enrich_session_meta_with_tenant(sid, user)
    meta = load_session_account_meta(sid)
    return meta if meta else {}


def _account_profile_fields(user: Any, session_meta: dict[str, Any]) -> dict[str, Any]:
    """账号体系真相源字段（暴露给前端只读展示）：tier / account_tier / budget_range /
    entitled_industries / market_membership_tier。account_tier 经派生（非企业为 None）。"""
    from app.application.account_tier_derivation import resolve_account_tier_for_user

    tier = str(getattr(user, "tier", "") or "") if user is not None else ""
    return {
        "tier": tier or None,
        "account_tier": resolve_account_tier_for_user(tier, getattr(user, "account_tier", None)),
        "budget_range": getattr(user, "budget_range", None) if user is not None else None,
        "entitled_industries": list(getattr(user, "entitled_industries", None) or []),
        "market_membership_tier": session_meta.get("market_membership_tier"),
        "email_verified": bool(getattr(user, "email_verified", False))
        if user is not None
        else False,
        "mfa_enabled": bool(getattr(user, "mfa_enabled", False)) if user is not None else False,
    }


@router.get("/api/auth/me")
def auth_me(request: Request):
    from app.application.auth_app_service import get_auth_app_service

    user = resolve_session_user(request)
    if not user:
        # 与 /api/auth/session/validate 一致：未登录用 200，避免前端 fetch 在控制台刷 401。
        return JSONResponse(
            {**error_envelope(UNAUTHORIZED, "请先登录"), "valid": False},
            status_code=200,
        )
    if not getattr(user, "is_active", True):
        return JSONResponse(
            error_envelope(ACCOUNT_DISABLED, "账户已被禁用"),
            status_code=403,
        )

    auth_app_service = get_auth_app_service()
    permissions = auth_app_service.get_user_permissions(user)
    session_meta = _session_meta_for_response(request, user)
    return {
        "success": True,
        "data": {
            "user": _user_public_dict(user),
            "permissions": permissions,
            "account_kind": session_meta.get("account_kind") or "enterprise",
            "company_brand": session_meta.get("company_brand") or "",
            "market_is_admin": bool(session_meta.get("market_is_admin")),
            "market_is_enterprise": bool(session_meta.get("market_is_enterprise")),
            "market_user_id": session_meta.get("market_user_id"),
            "local_user_id": session_meta.get("local_user_id") or getattr(user, "id", None),
            "tenant_id": session_meta.get("tenant_id"),
            "tenant_name": session_meta.get("tenant_name")
            or session_meta.get("company_brand")
            or "",
            "impersonating_market_user_id": session_meta.get("impersonating_market_user_id"),
            "impersonating_username": session_meta.get("impersonating_username") or "",
            **_account_profile_fields(user, session_meta),
        },
    }


@router.post("/api/auth/mfa/setup")
def auth_mfa_setup(request: Request):
    """生成 TOTP 密钥（待验证；mfa_enabled 在 /enable 校验通过后才置 True）。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
    from app.application.account_security import generate_totp_secret, provisioning_uri
    from app.db.models.user import User
    from app.db.session import get_db

    secret = generate_totp_secret()
    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return JSONResponse(error_envelope(UNAUTHORIZED, "用户不存在"), status_code=200)
        u.totp_secret = secret
        db.commit()
        username = u.username
    return {
        "success": True,
        "data": {"secret": secret, "otpauth_uri": provisioning_uri(secret, username)},
    }


@router.post("/api/auth/mfa/enable")
def auth_mfa_enable(request: Request, body: dict = Body(default_factory=dict)):
    """校验 TOTP 后开启 MFA。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
    code = str(body.get("code") or body.get("totp_code") or "").strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None or not (u.totp_secret or ""):
            return JSONResponse(
                error_envelope(INVALID_INPUT, "请先调用 /api/auth/mfa/setup 生成密钥"),
                status_code=400,
            )
        if not verify_totp(u.totp_secret, code):
            return JSONResponse(error_envelope(INVALID_INPUT, "动态验证码错误"), status_code=400)
        u.mfa_enabled = True
        db.commit()
    return {"success": True, "message": "MFA 已开启"}


@router.post("/api/auth/mfa/disable")
def auth_mfa_disable(request: Request, body: dict = Body(default_factory=dict)):
    """关闭 MFA（已开启时需校验当前 TOTP）。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(error_envelope(UNAUTHORIZED, "请先登录"), status_code=200)
    code = str(body.get("code") or body.get("totp_code") or "").strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return JSONResponse(error_envelope(UNAUTHORIZED, "用户不存在"), status_code=200)
        if u.mfa_enabled and not verify_totp(u.totp_secret or "", code):
            return JSONResponse(error_envelope(INVALID_INPUT, "动态验证码错误"), status_code=400)
        u.mfa_enabled = False
        u.totp_secret = None
        db.commit()
    return {"success": True, "message": "MFA 已关闭"}


@router.post("/api/auth/token/refresh")
def auth_token_refresh(body: dict = Body(default_factory=dict)):
    """无状态 JWT：用 refresh token 轮转出新的 access/refresh（一次性使用）。"""
    from app.security.web_jwt import refresh_web_access_token

    rt = str(body.get("refresh_token") or "").strip()
    tokens = refresh_web_access_token(rt)
    if not tokens:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "refresh token 无效或已使用"), status_code=401
        )
    return {"success": True, "data": tokens}


@router.get("/api/auth/session/validate")
async def auth_session_validate(request: Request):
    from app.application.auth_app_service import get_auth_app_service

    session_id = session_id_from_request(request)
    if not session_id:
        # 使用 200：避免前端 api.get 将「未登录」当成 HTTP 错误刷屏；语义由 success/valid 表达。
        return JSONResponse(
            {**error_envelope(NO_SESSION, "无会话信息"), "valid": False},
            status_code=200,
        )
    auth_app_service = get_auth_app_service()
    session_info = auth_app_service.session_manager.get_session_info(session_id)
    if not session_info:
        return JSONResponse(
            {**error_envelope(INVALID_SESSION, "会话无效或已过期"), "valid": False},
            status_code=200,
        )

    try:
        from app.mod_sdk.product_skus import resolve_product_sku

        if resolve_product_sku() == "enterprise":
            from app.fastapi_routes.market_account import resolve_valid_market_access_token

            market_tok = await resolve_valid_market_access_token(session_id)
            if not market_tok:
                return JSONResponse(
                    {
                        **error_envelope(
                            MARKET_NOT_BOUND,
                            (
                                "企业版需使用修茈市场企业级账号登录。"
                                "若此前仅用本地管理员进入，请退出后重新登录。"
                            ),
                        ),
                        "valid": False,
                    },
                    status_code=200,
                )
    except INFRA_TRANSIENT:
        logger.exception("enterprise market session check on validate failed")

    entitled_mod_ids: list[str] = []
    try:
        from app.enterprise.mod_entitlements import (
            get_cached_entitled_client_mod_ids,
            sync_entitlements_for_session,
        )

        entitled = await sync_entitlements_for_session(session_id)
        if entitled:
            entitled_mod_ids = sorted(entitled)
        else:
            cached = get_cached_entitled_client_mod_ids()
            if cached is not None:
                entitled_mod_ids = sorted(cached)
    except INFRA_TRANSIENT:
        logger.exception("sync enterprise entitlements on validate failed")
    user = resolve_session_user(request)
    session_meta = _session_meta_for_response(request, user)
    payload: dict[str, Any] = {"success": True, "valid": True, "data": session_info}
    if entitled_mod_ids:
        payload["entitled_mod_ids"] = entitled_mod_ids
    if session_meta:
        payload["account_kind"] = session_meta.get("account_kind")
        payload["company_brand"] = session_meta.get("company_brand")
        payload["market_is_admin"] = session_meta.get("market_is_admin")
        payload["market_is_enterprise"] = session_meta.get("market_is_enterprise")
        payload["market_user_id"] = session_meta.get("market_user_id")
        payload["local_user_id"] = session_meta.get("local_user_id")
        payload["tenant_id"] = session_meta.get("tenant_id")
        payload["tenant_name"] = session_meta.get("tenant_name")
        payload["impersonating_market_user_id"] = session_meta.get("impersonating_market_user_id")
        payload["impersonating_username"] = session_meta.get("impersonating_username")
        payload.update(_account_profile_fields(user, session_meta))
    return payload


def _market_user_email_from_raw(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    user = raw.get("user")
    if isinstance(user, dict) and user.get("email"):
        return str(user.get("email") or "").strip()
    data = raw.get("data")
    if isinstance(data, dict):
        inner = data.get("user")
        if isinstance(inner, dict) and inner.get("email"):
            return str(inner.get("email") or "").strip()
    return ""


def _normalize_auth_email(email: str) -> str:
    return (email or "").strip().lower()


def _find_local_users_by_email(email: str) -> list:
    from sqlalchemy import func

    from app.db.models.user import User
    from app.db.session import get_db

    norm = _normalize_auth_email(email)
    if not norm or "@" not in norm:
        return []
    with get_db() as db:
        return cast(
            "list[Any]",
            db.query(User)
            .filter(func.lower(User.email) == norm)
            .filter(User.is_active.is_(True))
            .order_by(User.id.asc())
            .all(),
        )


def _sync_local_password_for_email(email: str, new_password: str) -> int:
    from app.application.auth_app_service import get_auth_app_service

    auth_app_service = get_auth_app_service()
    updated = 0
    for user in _find_local_users_by_email(email):
        result = auth_app_service.reset_password(int(user.id), new_password)
        if result.get("success"):
            updated += 1
    return updated


def _jit_create_local_user_for_enterprise(username: str, password: str, email: str = "") -> bool:
    from app.db.models.user import User
    from app.db.session import get_db
    from app.utils.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    try:
        with get_db() as db:
            if db.query(User).filter(User.username == username).first():
                return False
            db.add(
                User(
                    username=username,
                    password=generate_password_hash(password),
                    display_name=username,
                    email=email or "",
                    role="user",
                    is_active=True,
                    mfa_enabled=False,
                    created_at=utc_now_naive(),
                )
            )
            db.commit()
        return True
    except INFRA_TRANSIENT as exc:
        logger.exception("_jit_create_local_user_for_enterprise failed for %s: %s", username, exc)
        return False


@router.get("/api/runtime/product-sku")
def runtime_product_sku():
    from app.mod_sdk.product_skus import resolve_product_sku

    sku = resolve_product_sku()
    return {
        "success": True,
        "data": {"sku": sku or "generic", "is_enterprise_edition": sku == "enterprise"},
    }


def _open_registration_allowed(sku: str) -> bool:
    raw = (os.environ.get("FHD_ALLOW_OPEN_REGISTRATION") or "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return sku != "enterprise"


def _enrich_register_with_tenant(
    *,
    result: dict[str, Any],
    username: str,
    session_id: str | None,
    sku: str,
    company_brand: str = "",
) -> dict[str, Any]:
    """注册成功后创建试用租户并写入会话元数据（与登录流 bind_tenant_for_login 对齐）。"""
    user_id = (result.get("user") or {}).get("id")
    if user_id is None:
        return result
    try:
        from app.application.enterprise_login_flow import bind_tenant_for_login
        from app.application.session_account_meta import persist_session_account_meta

        tenant_info = bind_tenant_for_login(
            user_id=int(user_id),
            company_brand=company_brand or username,
            username=username,
        )
        if tenant_info.get("tenant_id") is not None:
            result["tenant_id"] = tenant_info["tenant_id"]
        if tenant_info.get("tenant_name"):
            result["tenant_name"] = tenant_info["tenant_name"]
        if session_id:
            account_kind = "enterprise" if sku == "enterprise" else "personal"
            persist_session_account_meta(
                str(session_id),
                account_kind=account_kind,
                company_brand=company_brand or "",
                tenant_id=(int(tenant_info["tenant_id"]) if tenant_info.get("tenant_id") else None),
            )
            result.setdefault("account_kind", account_kind)
    except INFRA_TRANSIENT:
        logger.exception("register tenant provision failed for user_id=%s", user_id)
    return result


@router.get("/api/auth/subscription/status")
def auth_subscription_status(request: Request):
    """当前登录用户的试用/付费订阅状态（SaasPricingView 与订阅门禁共用）。"""
    user = resolve_session_user(request)
    if not user:
        return JSONResponse(
            error_envelope(UNAUTHORIZED, "请先登录"),
            status_code=200,
        )
    from app.application.tenant_subscription_app_service import subscription_status_for_user

    status = subscription_status_for_user(int(user.id))
    return {"success": True, "data": status}


def _attach_session_cookie(response: JSONResponse, session_id: str | None) -> JSONResponse:
    sid = (session_id or "").strip()
    if not sid:
        return response
    cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session_id")
    max_age = int(os.environ.get("SESSION_COOKIE_MAX_AGE", "315360000"))
    response.set_cookie(
        key=cookie_name,
        value=sid,
        max_age=max_age,
        httponly=os.environ.get("SESSION_COOKIE_HTTPONLY", "1") not in ("0", "false", "False"),
        secure=os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
        samesite=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
        path="/",
    )
    return response


@router.post("/api/auth/forgot-account")
def auth_forgot_account(body: dict = Body(default_factory=dict)):
    """Look up local PostgreSQL users by email (same DB as login)."""
    email = _normalize_auth_email(str(body.get("email") or ""))
    if not email or "@" not in email:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "请填写有效邮箱"),
            status_code=400,
        )
    users = _find_local_users_by_email(email)
    usernames = [str(u.username) for u in users if u.username]
    if usernames:
        message = f"找到 {len(usernames)} 个与本机数据库关联的账号"
    else:
        message = "本机数据库中未找到该邮箱对应的账号，可尝试注册或联系管理员"
    return {
        "success": True,
        "message": message,
        "data": {"usernames": usernames, "found": bool(usernames)},
    }


@router.post("/api/auth/forgot-password/send-code")
async def auth_forgot_password_send_code(body: dict = Body(default_factory=dict)):
    """Send reset code via Xiuci market API; uses XCAGI_MARKET_BASE_URL (e.g. production server)."""
    from app.fastapi_routes.market_account import send_market_reset_password_code

    email = _normalize_auth_email(str(body.get("email") or ""))
    if not email or "@" not in email:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "请填写有效邮箱"),
            status_code=400,
        )
    local_users = _find_local_users_by_email(email)
    try:
        from app.application.auth_app_service import get_auth_app_service

        svc = get_auth_app_service()
        send_local = getattr(svc, "send_password_reset_code", None)
        if callable(send_local):
            local_result = send_local(email)
            if isinstance(local_result, dict) and local_result.get("success"):
                return {
                    "success": True,
                    "message": local_result.get("message", "若该邮箱已注册，将收到验证码"),
                    "data": {"local_user_count": len(local_users)},
                }
    except Exception:  # noqa: BLE001
        pass
    result = await send_market_reset_password_code(email)
    if not result.get("success"):
        hint = result.get("message", "发送失败")
        if local_users:
            hint = f"{hint}（本机库中有该邮箱用户，请确认修茈市场服务与邮件配置正常）"
        return JSONResponse(
            error_envelope(SEND_CODE_FAILED, hint),
            status_code=502,
        )
    return {
        "success": True,
        "message": result.get("message", "若该邮箱已注册，将收到验证码"),
        "data": {
            "market_base_url": result.get("market_base_url"),
            "local_user_count": len(local_users),
        },
    }


@router.post("/api/auth/forgot-password/reset")
async def auth_forgot_password_reset(body: dict = Body(default_factory=dict)):
    """Reset password on market, then sync matching users in local PostgreSQL."""
    from app.fastapi_routes.market_account import reset_market_password_with_code

    email = _normalize_auth_email(str(body.get("email") or ""))
    code = str(body.get("code") or body.get("verification_code") or "").strip()
    new_password = str(body.get("new_password") or body.get("password") or "")
    if not email or "@" not in email:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "请填写有效邮箱"),
            status_code=400,
        )
    if len(new_password) < 6:
        return JSONResponse(
            error_envelope(WEAK_PASSWORD, "新密码至少 6 个字符"),
            status_code=400,
        )
    market_result = await reset_market_password_with_code(email, code, new_password)
    if not market_result.get("success"):
        return JSONResponse(
            error_envelope(MARKET_RESET_FAILED, market_result.get("message", "重置失败")),
            status_code=400,
        )
    local_updated = _sync_local_password_for_email(email, new_password)
    return {
        "success": True,
        "message": "密码已重置，请使用新密码登录",
        "data": {"local_users_updated": local_updated},
    }


@router.post("/api/auth/register")
async def auth_register(request: Request, body: dict = Body(default_factory=dict)):
    """Register locally (PostgreSQL users) and optionally on Xiuci market; then create session."""
    from app.application import get_user_app_service
    from app.application.auth_app_service import get_auth_app_service
    from app.fastapi_routes.market_account import (
        ensure_market_enterprise_profile,
        enterprise_mod_ids_for_industry,
        login_market_with_password,
        register_market_user,
        save_session_market_token,
    )
    from app.mod_sdk.product_skus import resolve_product_sku

    username = (body.get("username") or "").strip()
    password = body.get("password", "")
    email = (body.get("email") or "").strip()
    verification_code = str(body.get("verification_code") or body.get("code") or "").strip()
    # 账号体系：行业 + 预算区间（预算 → account_tier 自动派生）
    industry_id = (body.get("industry_id") or "").strip()
    budget_range = (body.get("budget_range") or "").strip()

    if not username or not password:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "用户名和密码不能为空"),
            status_code=400,
        )
    if len(password) < 6:
        return JSONResponse(
            error_envelope(WEAK_PASSWORD, "密码至少 6 个字符"),
            status_code=400,
        )

    sku = resolve_product_sku() or "generic"
    auth_app_service = get_auth_app_service()

    if sku == "enterprise":
        if not email:
            return JSONResponse(
                error_envelope(INVALID_INPUT, "企业版注册需填写邮箱"),
                status_code=400,
            )
        market_reg = await register_market_user(username, password, email, verification_code)
        if not market_reg.get("success"):
            return JSONResponse(
                error_envelope(
                    MARKET_REGISTER_FAILED,
                    market_reg.get("message", "修茈市场注册失败"),
                ),
                status_code=400,
            )
        email_market = _market_user_email_from_raw(market_reg.get("raw")) or email
        enterprise_profile = await ensure_market_enterprise_profile(
            market_reg.get("market_user_id"),
            username=username,
            company=email_market or email,
            mod_ids=enterprise_mod_ids_for_industry(industry_id),
        )
        if not enterprise_profile.get("success"):
            return JSONResponse(
                error_envelope(
                    MARKET_REGISTER_FAILED,
                    enterprise_profile.get("message", "修茈市场企业标记失败"),
                ),
                status_code=502,
            )
        _jit_create_local_user_for_enterprise(username, password, email_market)
        result = auth_app_service.login(username, password)
        if not result.get("success"):
            return JSONResponse(
                error_envelope(
                    LOCAL_LOGIN_AFTER_REGISTER,
                    result.get("message", "注册成功但本地登录失败"),
                ),
                status_code=500,
            )
        session_id = result.get("session_id")
        mtok = str(market_reg.get("token") or "").strip()
        mrefresh = str(market_reg.get("refresh_token") or "").strip()
        if session_id and mtok:
            save_session_market_token(str(session_id), mtok, mrefresh or None)
            result["market_access_token"] = mtok
            if mrefresh:
                result["market_refresh_token"] = mrefresh
        result = _enrich_register_with_tenant(
            result=result,
            username=username,
            session_id=str(session_id) if session_id else None,
            sku=sku,
            company_brand=email_market or email,
        )
    else:
        if not _open_registration_allowed(sku):
            return JSONResponse(
                error_envelope(
                    REGISTRATION_DISABLED,
                    "本部署未开放自助注册，请联系管理员创建账号",
                ),
                status_code=403,
            )
        user_service = get_user_app_service()
        created = user_service.create_user(
            username=username,
            password=password,
            display_name=(body.get("display_name") or username),
            email=email,
            role="viewer",
        )
        if not created.get("success"):
            msg = created.get("message", "创建用户失败")
            if "已存在" in msg or "unique" in msg.lower():
                msg = "用户名已存在"
            return JSONResponse(
                error_envelope(CREATE_FAILED, msg),
                status_code=400,
            )
        result = auth_app_service.login(username, password)
        if not result.get("success"):
            return JSONResponse(
                error_envelope(
                    LOGIN_AFTER_REGISTER,
                    result.get("message", "注册成功但登录失败"),
                ),
                status_code=500,
            )
        session_id = result.get("session_id")
        try:
            market_result = await login_market_with_password(username, password)
            if market_result.get("success"):
                mtok = str(market_result.get("token") or "").strip()
                mrefresh = str(market_result.get("refresh_token") or "").strip()
                if session_id and mtok:
                    save_session_market_token(str(session_id), mtok, mrefresh or None)
                    result["market_access_token"] = mtok
                    if mrefresh:
                        result["market_refresh_token"] = mrefresh
        except INFRA_TRANSIENT:
            logger.exception("optional market sync after local register failed")

        result = _enrich_register_with_tenant(
            result=result,
            username=username,
            session_id=str(session_id) if session_id else None,
            sku=sku,
            company_brand=email or username,
        )

    # 单一真相源 + 自动派生：写入 tier/industry_id/budget_range/account_tier/entitled_industries
    from app.application.account_registration import apply_account_profile_on_register
    from app.application.tenant_workspace_prefs import bind_selected_industry_for_username

    apply_account_profile_on_register(
        username,
        tier="enterprise" if sku == "enterprise" else "personal",
        industry_id=industry_id,
        budget_range=budget_range,
    )
    if industry_id:
        bind_selected_industry_for_username(username, industry_id)

    payload = {"success": True, **result}
    return _attach_session_cookie(JSONResponse(payload), result.get("session_id"))


@router.post("/api/auth/login")
async def auth_login(request: Request, body: dict = Body(default_factory=dict)):
    import time

    from app.utils.metrics import auth_login_duration_seconds

    login_start = time.perf_counter()
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import run_market_first_login
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.market_account import login_market_with_password
    from app.mod_sdk.product_skus import resolve_product_sku

    username = (body.get("username") or "").strip()
    password = body.get("password", "")
    if not username or not password:
        auth_login_duration_seconds.labels(auth_method="password").observe(
            time.perf_counter() - login_start
        )
        return JSONResponse(
            error_envelope(INVALID_INPUT, "用户名和密码不能为空"),
            status_code=200,
        )

    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku()
    account_kind = normalize_account_kind(
        body.get("account_kind"),
        default="enterprise" if sku == "enterprise" else "personal",
    )
    logger.info(
        "auth_login received username=%s sku=%s account_kind=%s has_password=%s",
        username,
        sku,
        account_kind,
        bool(password),
    )
    result, err = await run_market_first_login(
        username=username,
        password=password,
        account_kind=account_kind,
        market_result=None,
        auth_app_service=auth_app_service,
        sku=sku,
        jit_create_fn=_jit_create_local_user_for_enterprise,
        market_user_email_from_raw=_market_user_email_from_raw,
        login_market_fn=login_market_with_password,
        totp_code=str(body.get("totp_code") or "").strip() or None,
    )
    if err:
        auth_login_duration_seconds.labels(auth_method="password").observe(
            time.perf_counter() - login_start
        )
        return err
    # 增量无状态 JWT：附带签发 web token（前端/API 客户端可选用；不影响 session cookie）
    if result and result.get("success"):
        _u = result.get("user") or {}
        if _u.get("id") is not None:
            try:
                from app.security.web_jwt import issue_web_tokens

                result["web_tokens"] = issue_web_tokens(
                    user_id=int(_u["id"]),
                    username=str(_u.get("username") or ""),
                    account_kind=str(result.get("account_kind") or "enterprise"),
                )
            except INFRA_TRANSIENT:
                logger.exception("issue web tokens failed")
    resp = _attach_session_cookie(JSONResponse(result or {}), (result or {}).get("session_id"))
    auth_login_duration_seconds.labels(auth_method="password").observe(
        time.perf_counter() - login_start
    )
    return resp


@router.post("/api/auth/login-with-phone-code")
async def auth_login_with_phone_code(request: Request, body: dict = Body(default_factory=dict)):
    import time

    from app.utils.metrics import auth_login_duration_seconds

    login_start = time.perf_counter()
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import run_market_first_login
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.market_account import login_market_with_phone_code
    from app.mod_sdk.product_skus import resolve_product_sku

    phone = str(body.get("phone") or "").strip()
    code = str(body.get("code") or "").strip()
    if not phone or not code:
        auth_login_duration_seconds.labels(auth_method="phone_code").observe(
            time.perf_counter() - login_start
        )
        return JSONResponse(
            error_envelope(INVALID_INPUT, "手机号和验证码不能为空"),
            status_code=400,
        )

    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku()
    account_kind = normalize_account_kind(
        body.get("account_kind"),
        default="enterprise" if sku == "enterprise" else "personal",
    )
    market_result = await login_market_with_phone_code(phone, code)
    username = str(body.get("username") or "").strip()
    result, err = await run_market_first_login(
        username=username,
        password=None,
        account_kind=account_kind,
        market_result=market_result,
        auth_app_service=auth_app_service,
        sku=sku,
        jit_create_fn=_jit_create_local_user_for_enterprise,
        market_user_email_from_raw=_market_user_email_from_raw,
        login_market_fn=None,
    )
    if err:
        auth_login_duration_seconds.labels(auth_method="phone_code").observe(
            time.perf_counter() - login_start
        )
        return err
    resp = _attach_session_cookie(JSONResponse(result or {}), (result or {}).get("session_id"))
    auth_login_duration_seconds.labels(auth_method="phone_code").observe(
        time.perf_counter() - login_start
    )
    return resp


@router.get("/api/auth/oidc/status")
def auth_oidc_status():
    from app.infrastructure.auth.oidc_provider import oidc_enabled

    return {"success": True, "data": {"enabled": oidc_enabled()}}


@router.get("/api/auth/oidc/start")
async def auth_oidc_start(request: Request):
    from fastapi.responses import RedirectResponse

    from app.infrastructure.auth.oidc_provider import (
        build_authorize_url,
        oidc_enabled,
        sign_oidc_state,
    )

    if not oidc_enabled():
        return JSONResponse({"success": False, "message": "OIDC 未启用"}, status_code=404)
    return_to = str(request.query_params.get("return") or "").strip()
    state = sign_oidc_state(return_to=return_to)
    url = await build_authorize_url(state=state)
    return RedirectResponse(url=url, status_code=302)


@router.get("/api/auth/oidc/callback")
async def auth_oidc_callback(request: Request):
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse

    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import finalize_auth_after_oidc
    from app.application.session_account_meta import normalize_account_kind
    from app.infrastructure.auth.oidc_provider import (
        exchange_oidc_authorization,
        frontend_redirect_path,
        oidc_enabled,
        verify_oidc_state,
    )
    from app.mod_sdk.product_skus import resolve_product_sku

    base = frontend_redirect_path()
    if not oidc_enabled():
        return RedirectResponse(url=f"{base}?oidc_error=OIDC_DISABLED", status_code=302)

    code = str(request.query_params.get("code") or "").strip()
    state = str(request.query_params.get("state") or "").strip()
    ok, _rt = verify_oidc_state(state)
    if not ok or not code:
        return RedirectResponse(
            url=f"{base}?oidc_error=OIDC_STATE&oidc_message={quote('状态校验失败')}",
            status_code=302,
        )

    try:
        oidc_session = await exchange_oidc_authorization(code)
        profile = (
            oidc_session.get("profile") if isinstance(oidc_session.get("profile"), dict) else {}
        )
    except INFRA_TRANSIENT as exc:
        logger.exception("OIDC exchange failed")
        return RedirectResponse(
            url=f"{base}?oidc_error=OIDC_EXCHANGE&oidc_message={quote(str(exc))}",
            status_code=302,
        )

    auth_app_service = get_auth_app_service()
    auth_result = auth_app_service.authenticate_oidc_user(profile)
    if not auth_result.get("success"):
        msg = str(auth_result.get("message") or "OIDC 登录失败")
        return RedirectResponse(
            url=f"{base}?oidc_error=OIDC_AUTH&oidc_message={quote(msg)}",
            status_code=302,
        )

    sku = resolve_product_sku()
    account_kind = normalize_account_kind(
        request.query_params.get("account_kind"),
        default="enterprise" if sku == "enterprise" else "personal",
    )
    payload = await finalize_auth_after_oidc(
        auth_result=auth_result,
        oidc_profile=profile,
        oidc_access_token=str(oidc_session.get("access_token") or ""),
        account_kind=account_kind,
        sku=sku,
    )
    resp = RedirectResponse(url=f"{base}?oidc=ok", status_code=302)
    return _attach_session_cookie(resp, payload.get("session_id"))


@router.post("/api/auth/qr/issue")
async def auth_qr_issue(request: Request, body: dict = Body(default_factory=dict)):
    from app.application.session_account_meta import normalize_account_kind
    from app.security.auth_qr_login import issue_auth_qr

    client_hint = str(body.get("client_hint") or request.headers.get("User-Agent") or "")[:256]
    kwargs: dict[str, Any] = {"client_hint": client_hint}
    if "account_kind" in body:
        kwargs["account_kind"] = normalize_account_kind(
            body.get("account_kind"), default="enterprise"
        )
    data = issue_auth_qr(**kwargs)
    return {"success": True, "data": data}


@router.get("/api/auth/qr/status")
async def auth_qr_status(qr_id: str = Query(""), poll_secret: str = Query("")):
    from app.security.auth_qr_login import consume_confirmed_qr, poll_auth_qr

    rec = poll_auth_qr(qr_id, poll_secret)
    if not rec:
        return JSONResponse(
            error_envelope(QR_NOT_FOUND, "二维码无效"),
            status_code=404,
        )
    status = str(rec.get("status") or "pending")
    if status == "confirmed":
        confirmed = consume_confirmed_qr(qr_id, poll_secret)
        if confirmed and confirmed.get("session_id"):
            payload = confirmed.get("login_payload") or {}
            resp = JSONResponse(
                {
                    "success": True,
                    "data": {
                        "status": "confirmed",
                        "session_id": confirmed.get("session_id"),
                        **payload,
                    },
                }
            )
            return _attach_session_cookie(resp, str(confirmed.get("session_id")))
    if status == "expired":
        return {"success": True, "data": {"status": "expired"}}
    return {"success": True, "data": {"status": status}}


@router.get("/api/auth/profile")
def auth_profile_get(user=Depends(get_logged_in_user)):
    """当前用户个人资料（展示名、邮箱、头像）。"""
    return {"success": True, "data": {"user": _user_public_dict(user)}}


@router.patch("/api/auth/profile")
def auth_profile_patch(body: dict = Body(default_factory=dict), user=Depends(get_logged_in_user)):
    """更新当前用户展示名与邮箱。"""
    from app.application.user_app_service import get_user_app_service

    display_name = body.get("display_name")
    email = body.get("email")
    kwargs: dict[str, Any] = {}
    if display_name is not None:
        kwargs["display_name"] = str(display_name).strip()[:64]
    if email is not None:
        kwargs["email"] = str(email).strip()[:128]
    if not kwargs:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "无有效字段"),
            status_code=400,
        )
    result = get_user_app_service().update_user(user.id, **kwargs)
    if not result.get("success"):
        return JSONResponse(
            error_envelope(UPDATE_FAILED, result.get("message", "更新失败")),
            status_code=400,
        )
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        row = db.query(User).filter(User.id == user.id).first()
        if row is None:
            return JSONResponse(
                error_envelope(NOT_FOUND, "用户不存在"),
                status_code=404,
            )
        payload = _user_public_dict(row)
    return {"success": True, "data": {"user": payload}}


@router.post("/api/auth/profile/avatar")
async def auth_profile_avatar_upload(
    file: UploadFile | None = File(default=None),
    user=Depends(get_logged_in_user),
):
    """上传并替换当前用户头像（png/jpg/gif/webp，≤4MB）。"""
    if file is None or not file.filename:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "请选择图片文件"),
            status_code=400,
        )
    from app.utils.secure_filename import secure_filename
    from app.utils.user_avatar_storage import (
        AVATAR_API_PATH,
        save_user_avatar_file,
    )

    safe_name = secure_filename(file.filename) or "avatar.png"
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else "png"
    content = await file.read()
    try:
        save_user_avatar_file(user.id, content, ext)
    except ValueError as exc:
        return JSONResponse(
            error_envelope(INVALID_FILE, str(exc)),
            status_code=400,
        )
    except OSError as exc:
        logger.exception("avatar save failed user_id=%s", user.id)
        return JSONResponse(
            error_envelope(SAVE_FAILED, f"头像保存失败：{exc}"),
            status_code=500,
        )

    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        row = db.query(User).filter(User.id == user.id).first()
        if row is not None:
            row.wx_avatar_url = AVATAR_API_PATH
    return {
        "success": True,
        "data": {"avatar_url": AVATAR_API_PATH},
    }


@router.get("/api/auth/avatar")
def auth_profile_avatar_get(user=Depends(get_logged_in_user)):
    """返回当前登录用户的头像文件（依赖会话 Cookie 或 Bearer）。"""
    from app.utils.user_avatar_storage import avatar_file_for_user, media_type_for_path

    path = avatar_file_for_user(user.id)
    if path is None:
        return JSONResponse(status_code=404, content={"success": False, "message": "未设置头像"})
    return FileResponse(str(path), media_type=media_type_for_path(path))


@router.post("/api/auth/company-brand")
async def auth_update_company_brand(
    request: Request, body: dict = Body(default_factory=dict), user=Depends(get_logged_in_user)
):
    """更新企业品牌名（写入 session，并同步修茈市场 user.company）。"""
    brand = str(body.get("company_brand") or body.get("company") or "").strip()[:256]
    sid = session_id_from_request(request)
    if not sid:
        return JSONResponse(
            error_envelope(NO_SESSION, "无会话"),
            status_code=400,
        )
    from app.application.session_account_meta import (
        load_session_account_meta,
        persist_session_account_meta,
    )
    from app.fastapi_routes.market_account import _proxy_json, resolve_valid_market_access_token

    meta = load_session_account_meta(sid) or {}
    persist_session_account_meta(
        sid,
        account_kind=str(meta.get("account_kind") or "enterprise"),
        company_brand=brand,
        market_user_id=meta.get("market_user_id"),
        market_is_admin=bool(meta.get("market_is_admin")),
        market_is_enterprise=bool(meta.get("market_is_enterprise")),
        impersonating_market_user_id=meta.get("impersonating_market_user_id"),
        impersonating_username=str(meta.get("impersonating_username") or ""),
    )
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
        await _proxy_json(
            "PUT",
            "/api/auth/profile",
            json_body={"company": brand},
            authorization=auth,
            return_error_payload=True,
        )
    return {"success": True, "company_brand": brand}


@router.post("/api/auth/logout")
def auth_logout(request: Request):
    from app.application.auth_app_service import get_auth_app_service
    from app.fastapi_routes.market_account import clear_session_market_token

    sid = session_id_from_request(request)
    if not sid:
        return JSONResponse(
            error_envelope(NO_SESSION, "无有效会话"),
            status_code=400,
        )
    auth_app_service = get_auth_app_service()
    result = auth_app_service.logout(sid)
    clear_session_market_token(sid)
    try:
        from app.enterprise.mod_entitlements import clear_session_entitlements

        clear_session_entitlements()
    except INFRA_TRANSIENT:
        pass
    resp = JSONResponse(result)
    cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session_id")
    resp.delete_cookie(cookie_name, path="/")
    return resp


@router.post("/api/auth/password/change")
def auth_password_change(body: dict = Body(default_factory=dict), user=Depends(get_logged_in_user)):
    from app.application.auth_app_service import get_auth_app_service

    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")
    if not old_password or not new_password:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "请填写完整信息"),
            status_code=400,
        )
    if len(new_password) < 6:
        return JSONResponse(
            error_envelope(WEAK_PASSWORD, "新密码至少 6 个字符"),
            status_code=400,
        )
    auth_app_service = get_auth_app_service()
    result = auth_app_service.change_password(user.id, old_password, new_password)
    if not result["success"]:
        return JSONResponse(result, status_code=400)
    return result


@router.get("/api/users")
def users_list(include_inactive: str = Query(default="false"), _user=Depends(_require_admin)):
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    users = user_service.list_users(skip=0, limit=100)
    if include_inactive.lower() != "true":
        users = [u for u in users if u.get("is_active", True)]
    return {"success": True, "data": {"users": users, "count": len(users)}}


@router.get("/api/users/{user_id}")
def users_get(user_id: int, _user=Depends(_require_admin)):
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    user = user_service.get_user(user_id)
    if not user:
        return JSONResponse(
            error_envelope(NOT_FOUND, "用户不存在"),
            status_code=404,
        )
    return {"success": True, "data": {"user": user}}


@router.post("/api/users")
def users_create(body: dict = Body(default_factory=dict), _user=Depends(_require_admin)):
    from app.application import get_user_app_service

    username = (body.get("username") or "").strip()
    password = body.get("password", "")
    if not username or not password:
        return JSONResponse(
            error_envelope(INVALID_INPUT, "用户名和密码不能为空"),
            status_code=400,
        )
    if len(password) < 6:
        return JSONResponse(
            error_envelope(WEAK_PASSWORD, "密码至少6个字符"),
            status_code=400,
        )
    role = body.get("role", "viewer")
    if role not in ["viewer", "operator", "admin"]:
        return JSONResponse(
            error_envelope(INVALID_ROLE, "无效的角色"),
            status_code=400,
        )
    user_service = get_user_app_service()
    result = user_service.create_user(
        username=username,
        password=password,
        display_name=body.get("display_name", ""),
        email=body.get("email", ""),
        role=role,
    )
    if not result["success"]:
        return JSONResponse(
            error_envelope(CREATE_FAILED, result["error"]),
            status_code=400,
        )
    return JSONResponse({"success": True, "data": {"user": result["user"]}}, status_code=201)


@router.put("/api/users/{user_id}")
def users_update(
    user_id: int, body: dict = Body(default_factory=dict), _user=Depends(_require_admin)
):
    from app.application import get_user_app_service

    role = body.get("role")
    if role and role not in ["viewer", "operator", "admin"]:
        return JSONResponse(
            error_envelope(INVALID_ROLE, "无效的角色"),
            status_code=400,
        )
    user_service = get_user_app_service()
    result = user_service.update_user(
        user_id=user_id,
        display_name=body.get("display_name"),
        email=body.get("email"),
        role=role,
        is_active=body.get("is_active"),
    )
    if not result["success"]:
        return JSONResponse(
            error_envelope(UPDATE_FAILED, result["error"]),
            status_code=400,
        )
    return {"success": True, "data": {"user": result["user"]}}


@router.delete("/api/users/{user_id}")
def users_delete(user_id: int, user=Depends(_require_admin)):
    if user.id == user_id:
        return JSONResponse(
            error_envelope(SELF_DELETE, "不能删除自己"),
            status_code=400,
        )
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    result = user_service.delete_user(user_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    return result


@router.post("/api/users/{user_id}/reset-password")
def users_reset_password(
    user_id: int, body: dict = Body(default_factory=dict), _user=Depends(_require_admin)
):
    from app.application.auth_app_service import get_auth_app_service

    new_password = body.get("new_password", "")
    if not new_password:
        return JSONResponse(
            error_envelope(MISSING_PASSWORD, "新密码不能为空"),
            status_code=400,
        )
    if len(new_password) < 6:
        return JSONResponse(
            error_envelope(WEAK_PASSWORD, "密码至少6个字符"),
            status_code=400,
        )
    auth_app_service = get_auth_app_service()
    result = auth_app_service.reset_password(user_id, new_password)
    if not result["success"]:
        return JSONResponse(result, status_code=400)
    return result
