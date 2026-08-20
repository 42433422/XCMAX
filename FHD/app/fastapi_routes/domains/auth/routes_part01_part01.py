# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.auth.routes")


def _user_public_dict(user) -> dict[str, _facade().Any]:
    from app.utils.no_email import email_display, is_no_email_address
    from app.utils.path_io.user_avatar_storage import public_avatar_url

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "email_display": email_display(user.email),
        "no_email": is_no_email_address(user.email),
        "role": user.role,
        "is_active": user.is_active,
        "avatar_url": public_avatar_url(getattr(user, "wx_avatar_url", None)),
    }


def _session_meta_for_response(request: _facade().Request, user=None) -> dict[str, _facade().Any]:
    from app.application.session_account_meta import (
        enrich_session_meta_with_tenant,
        load_session_account_meta,
    )

    sid = _facade().session_id_from_request(request)
    if not sid:
        return {}
    if user is not None:
        return enrich_session_meta_with_tenant(sid, user)
    meta = load_session_account_meta(sid)
    return meta if meta else {}


def _account_profile_fields(
    user: _facade().Any, session_meta: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
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


@_facade().router.get("/api/auth/me")
def auth_me(request: _facade().Request):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.desktop_admin_gate import assert_desktop_allows_session_id

    denied = assert_desktop_allows_session_id(_facade().session_id_from_request(request))
    if denied is not None:
        return _facade().JSONResponse(denied, status_code=403)
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(
            {**_facade().error_envelope(_facade().UNAUTHORIZED, "请先登录"), "valid": False},
            status_code=200,
        )
    if not getattr(user, "is_active", True):
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().ACCOUNT_DISABLED, "账户已被禁用"), status_code=403
        )
    auth_app_service = get_auth_app_service()
    permissions = auth_app_service.get_user_permissions(user)
    session_meta = _facade()._session_meta_for_response(request, user)
    return {
        "success": True,
        "data": {
            "user": _facade()._user_public_dict(user),
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
            **_facade()._account_profile_fields(user, session_meta),
        },
    }


@_facade().router.post("/api/auth/mfa/setup")
def auth_mfa_setup(request: _facade().Request):
    """生成 TOTP 密钥（待验证；mfa_enabled 在 /enable 校验通过后才置 True）。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().UNAUTHORIZED, "请先登录"), status_code=200
        )
    from app.application.account_security import generate_totp_secret, provisioning_uri
    from app.db.models.user import User
    from app.db.session import get_db

    secret = generate_totp_secret()
    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return _facade().JSONResponse(
                _facade().error_envelope(_facade().UNAUTHORIZED, "用户不存在"), status_code=200
            )
        u.totp_secret = secret
        db.commit()
        username = u.username
    return {
        "success": True,
        "data": {"secret": secret, "otpauth_uri": provisioning_uri(secret, username)},
    }


@_facade().router.post("/api/auth/mfa/enable")
def auth_mfa_enable(request: _facade().Request, body: dict = _facade().Body(default_factory=dict)):
    """校验 TOTP 后开启 MFA。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().UNAUTHORIZED, "请先登录"), status_code=200
        )
    code = str(body.get("code") or body.get("totp_code") or "").strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None or not (u.totp_secret or ""):
            return _facade().JSONResponse(
                _facade().error_envelope(
                    _facade().INVALID_INPUT, "请先调用 /api/auth/mfa/setup 生成密钥"
                ),
                status_code=400,
            )
        if not verify_totp(u.totp_secret, code):
            return _facade().JSONResponse(
                _facade().error_envelope(_facade().INVALID_INPUT, "动态验证码错误"), status_code=400
            )
        u.mfa_enabled = True
        db.commit()
    return {"success": True, "message": "MFA 已开启"}


@_facade().router.post("/api/auth/mfa/disable")
def auth_mfa_disable(request: _facade().Request, body: dict = _facade().Body(default_factory=dict)):
    """关闭 MFA（已开启时需校验当前 TOTP）。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().UNAUTHORIZED, "请先登录"), status_code=200
        )
    code = str(body.get("code") or body.get("totp_code") or "").strip()
    from app.application.account_security import verify_totp
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        u = db.get(User, int(user.id))
        if u is None:
            return _facade().JSONResponse(
                _facade().error_envelope(_facade().UNAUTHORIZED, "用户不存在"), status_code=200
            )
        if u.mfa_enabled and (not verify_totp(u.totp_secret or "", code)):
            return _facade().JSONResponse(
                _facade().error_envelope(_facade().INVALID_INPUT, "动态验证码错误"), status_code=400
            )
        u.mfa_enabled = False
        u.totp_secret = None
        db.commit()
    return {"success": True, "message": "MFA 已关闭"}


@_facade().router.post("/api/auth/token/refresh")
def auth_token_refresh(body: dict = _facade().Body(default_factory=dict)):
    """无状态 JWT：用 refresh token 轮转出新的 access/refresh（一次性使用）。"""
    from app.security.web_jwt import refresh_web_access_token

    rt = str(body.get("refresh_token") or "").strip()
    tokens = refresh_web_access_token(rt)
    if not tokens:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "refresh token 无效或已使用"),
            status_code=401,
        )
    return {"success": True, "data": tokens}


@_facade().router.get("/api/auth/session/validate")
async def auth_session_validate(
    request: _facade().Request, background_tasks: _facade().BackgroundTasks
):
    from app.application.auth_app_service import get_auth_app_service
    from app.application.desktop_admin_gate import assert_desktop_allows_session_id

    session_id = _facade().session_id_from_request(request)
    if not session_id:
        return _facade().JSONResponse(
            {**_facade().error_envelope(_facade().NO_SESSION, "无会话信息"), "valid": False},
            status_code=200,
        )
    denied = assert_desktop_allows_session_id(session_id)
    if denied is not None:
        return _facade().JSONResponse(denied, status_code=403)
    auth_app_service = get_auth_app_service()
    session_info = auth_app_service.session_manager.get_session_info(session_id)
    if not session_info:
        return _facade().JSONResponse(
            {
                **_facade().error_envelope(_facade().INVALID_SESSION, "会话无效或已过期"),
                "valid": False,
            },
            status_code=200,
        )
    try:
        from app.mod_sdk.product_skus import resolve_product_sku

        if resolve_product_sku() == "enterprise":
            from app.fastapi_routes.market_account import resolve_valid_market_access_token_fast

            market_tok = await resolve_valid_market_access_token_fast(session_id)
            if not market_tok:
                return _facade().JSONResponse(
                    {
                        **_facade().error_envelope(
                            _facade().MARKET_NOT_BOUND,
                            "企业版需使用修茈市场企业级账号登录。若此前仅用本地管理员进入，请退出后重新登录。",
                        ),
                        "valid": False,
                    },
                    status_code=200,
                )
    except _facade().INFRA_TRANSIENT:
        _facade().logger.exception("enterprise market session check on validate failed")
    entitled_mod_ids: list[str] = []
    try:
        from app.enterprise.mod_entitlements import (
            get_cached_entitled_client_mod_ids,
            sync_entitlements_for_session,
        )

        background_tasks.add_task(sync_entitlements_for_session, session_id)
        cached = get_cached_entitled_client_mod_ids()
        if cached is not None:
            entitled_mod_ids = sorted(cached)
    except _facade().INFRA_TRANSIENT:
        _facade().logger.exception("sync enterprise entitlements on validate failed")
    user = _facade().resolve_session_user(request)
    session_meta = _facade()._session_meta_for_response(request, user)
    payload: dict[str, _facade().Any] = {"success": True, "valid": True, "data": session_info}
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
        payload.update(_facade()._account_profile_fields(user, session_meta))
    return payload


def _market_user_email_from_raw(raw: _facade().Any) -> str:
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

    norm = _facade()._normalize_auth_email(email)
    if not norm or "@" not in norm:
        return []
    with get_db() as db:
        return _facade().cast(
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
    for user in _facade()._find_local_users_by_email(email):
        result = auth_app_service.reset_password(int(user.id), new_password)
        if result.get("success"):
            updated += 1
    return updated
