# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.auth.routes")


def _jit_create_local_user_for_enterprise(username: str, password: str, email: str = "") -> bool:
    from app.db.models.user import User
    from app.db.session import get_db
    from app.utils.security.password_hash import generate_password_hash
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
    except _facade().INFRA_TRANSIENT as exc:
        _facade().logger.exception(
            "_jit_create_local_user_for_enterprise failed for %s: %s", username, exc
        )
        return False


@_facade().router.get("/api/runtime/product-sku")
def runtime_product_sku():
    from app.mod_sdk.product_skus import resolve_product_sku

    sku = resolve_product_sku()
    return {
        "success": True,
        "data": {"sku": sku or "generic", "is_enterprise_edition": sku == "enterprise"},
    }


def _open_registration_allowed(sku: str) -> bool:
    raw = (_facade().os.environ.get("FHD_ALLOW_OPEN_REGISTRATION") or "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return sku != "enterprise"


def _enrich_register_with_tenant(
    *,
    result: dict[str, _facade().Any],
    username: str,
    session_id: str | None,
    sku: str,
    company_brand: str = "",
) -> dict[str, _facade().Any]:
    """注册成功后创建试用租户并写入会话元数据（与登录流 bind_tenant_for_login 对齐）。"""
    user_id = (result.get("user") or {}).get("id")
    if user_id is None:
        return result
    try:
        from app.application.enterprise_login_flow import bind_tenant_for_login
        from app.application.session_account_meta import (
            normalize_account_kind,
            persist_session_account_meta,
        )

        tenant_info = bind_tenant_for_login(
            user_id=int(user_id), company_brand=company_brand or username, username=username
        )
        if tenant_info.get("tenant_id") is not None:
            result["tenant_id"] = tenant_info["tenant_id"]
        if tenant_info.get("tenant_name"):
            result["tenant_name"] = tenant_info["tenant_name"]
        if session_id:
            account_kind = normalize_account_kind(
                "enterprise" if sku == "enterprise" else "personal"
            )
            persist_session_account_meta(
                str(session_id),
                account_kind=account_kind,
                company_brand=company_brand or "",
                tenant_id=int(tenant_info["tenant_id"]) if tenant_info.get("tenant_id") else None,
            )
            result.setdefault("account_kind", account_kind)
    except _facade().INFRA_TRANSIENT:
        _facade().logger.exception("register tenant provision failed for user_id=%s", user_id)
    return result


@_facade().router.get("/api/auth/subscription/status")
def auth_subscription_status(request: _facade().Request):
    """当前登录用户的试用/付费订阅状态（SaasPricingView 与订阅门禁共用）。"""
    user = _facade().resolve_session_user(request)
    if not user:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().UNAUTHORIZED, "请先登录"), status_code=200
        )
    from app.application.tenant_subscription_app_service import subscription_status_for_user

    status = subscription_status_for_user(int(user.id))
    return {"success": True, "data": status}


def _attach_session_cookie(
    response: _facade().Response, session_id: str | None
) -> _facade().Response:
    sid = (session_id or "").strip()
    if not sid:
        return response
    cookie_name = _facade().os.environ.get("SESSION_COOKIE_NAME", "session_id")
    max_age = int(_facade().os.environ.get("SESSION_COOKIE_MAX_AGE", "315360000"))
    raw_samesite = _facade().os.environ.get("SESSION_COOKIE_SAMESITE", "Lax").strip().lower()
    samesite = _facade().cast(
        "Literal['lax', 'strict', 'none']",
        raw_samesite if raw_samesite in {"lax", "strict", "none"} else "lax",
    )
    response.set_cookie(
        key=cookie_name,
        value=sid,
        max_age=max_age,
        httponly=_facade().os.environ.get("SESSION_COOKIE_HTTPONLY", "1")
        not in ("0", "false", "False"),
        secure=_facade().os.environ.get("SESSION_COOKIE_SECURE", "").lower()
        in ("1", "true", "yes"),
        samesite=samesite,
        path="/",
    )
    return response


@_facade().router.post("/api/auth/forgot-account")
def auth_forgot_account(body: dict = _facade().Body(default_factory=dict)):
    """Look up local PostgreSQL users by email (same DB as login)."""
    email = _facade()._normalize_auth_email(str(body.get("email") or ""))
    if not email or "@" not in email:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "请填写有效邮箱"), status_code=400
        )
    users = _facade()._find_local_users_by_email(email)
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


@_facade().router.post("/api/auth/forgot-password/send-code")
async def auth_forgot_password_send_code(body: dict = _facade().Body(default_factory=dict)):
    """Send reset code via Xiuci market API; uses XCAGI_MARKET_BASE_URL (e.g. production server)."""
    from app.fastapi_routes.market_account import send_market_reset_password_code

    email = _facade()._normalize_auth_email(str(body.get("email") or ""))
    if not email or "@" not in email:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "请填写有效邮箱"), status_code=400
        )
    local_users = _facade()._find_local_users_by_email(email)
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
    except _facade().RECOVERABLE_ERRORS:
        pass
    result = await send_market_reset_password_code(email)
    if not result.get("success"):
        hint = result.get("message", "发送失败")
        if local_users:
            hint = f"{hint}（本机库中有该邮箱用户，请确认修茈市场服务与邮件配置正常）"
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().SEND_CODE_FAILED, hint), status_code=502
        )
    return {
        "success": True,
        "message": result.get("message", "若该邮箱已注册，将收到验证码"),
        "data": {
            "market_base_url": result.get("market_base_url"),
            "local_user_count": len(local_users),
        },
    }


@_facade().router.post("/api/auth/forgot-password/reset")
async def auth_forgot_password_reset(body: dict = _facade().Body(default_factory=dict)):
    """Reset password on market, then sync matching users in local PostgreSQL."""
    from app.fastapi_routes.market_account import reset_market_password_with_code

    email = _facade()._normalize_auth_email(str(body.get("email") or ""))
    code = str(body.get("code") or body.get("verification_code") or "").strip()
    new_password = str(body.get("new_password") or body.get("password") or "")
    if not email or "@" not in email:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "请填写有效邮箱"), status_code=400
        )
    if len(new_password) < 6:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().WEAK_PASSWORD, "新密码至少 6 个字符"),
            status_code=400,
        )
    market_result = await reset_market_password_with_code(email, code, new_password)
    if not market_result.get("success"):
        return _facade().JSONResponse(
            _facade().error_envelope(
                _facade().MARKET_RESET_FAILED, market_result.get("message", "重置失败")
            ),
            status_code=400,
        )
    local_updated = _facade()._sync_local_password_for_email(email, new_password)
    return {
        "success": True,
        "message": "密码已重置，请使用新密码登录",
        "data": {"local_users_updated": local_updated},
    }
