"""企业版登录后置：市场 token 绑定、会话元数据、Mod 权益、租户绑定。"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi.responses import JSONResponse

from app.application.session_account_meta import (
    AccountKind,
    company_brand_from_user_blob,
    extract_market_user_blob,
    persist_session_account_meta,
    validate_account_kind_for_market,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _login_client_http_status(upstream_status: int) -> int:
    """凭证/业务拒绝用 200，避免前端 fetch 在控制台刷 401/403；仅 5xx 保留 HTTP 错误态。"""
    try:
        code = int(upstream_status)
    except (TypeError, ValueError):
        code = 502
    if code >= 500:
        return code
    return 200


def market_auth_error_response(market_result: dict[str, Any]) -> JSONResponse:
    try:
        status_code = int(market_result.get("status_code") or 0)
    except (TypeError, ValueError):
        status_code = 0
    if status_code < 400:
        status_code = 502
    message = str(market_result.get("message") or "修茈市场账号验证失败").strip()
    error_code = "MARKET_AUTH_UNAVAILABLE" if status_code >= 500 else "MARKET_AUTH_FAILED"
    return JSONResponse(
        {
            "success": False,
            "message": message,
            "error": {"code": error_code, "message": message},
            "market_account": {
                "success": False,
                "market_base_url": market_result.get("market_base_url"),
                "message": message,
            },
        },
        status_code=_login_client_http_status(status_code),
    )


def resolve_market_username(market_result: dict[str, Any]) -> str:
    blob = extract_market_user_blob(market_result)
    for key in ("username", "phone", "email"):
        val = str(blob.get(key) or "").strip()
        if val:
            return val
    raw = market_result.get("raw")
    if isinstance(raw, dict):
        for key in ("username", "phone"):
            val = str(raw.get(key) or "").strip()
            if val:
                return val
    return ""


async def ensure_local_user_after_market(
    *,
    username: str,
    password: str | None,
    market_result: dict[str, Any],
    auth_app_service: Any,
    jit_create_fn: Any,
    market_user_email_from_raw: Any,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """市场已通过：确保本地用户存在并创建 session。"""
    if password:
        # 市场已验证身份，本地仅二次确认密码：不在此处强制本地 MFA（市场是认证权威）
        result = auth_app_service.login(username, password, enforce_mfa=False)
        if result.get("success"):
            return result, None

    from app.db.models.user import User
    from app.db.session import get_db

    try:
        from app.db.init_db import ensure_runtime_auth_bootstrap

        ensure_runtime_auth_bootstrap(swallow_errors=True)
        with get_db() as db:
            exists = db.query(User).filter(User.username == username).first()
    except RECOVERABLE_ERRORS as db_exc:
        logger.exception("enterprise login user lookup failed")
        return None, JSONResponse(
            {
                "success": False,
                "error": {
                    "code": "DATABASE_ERROR",
                    "message": f"本地用户库不可用：{db_exc}",
                },
            },
            status_code=503,
        )

    if exists and password:
        return None, JSONResponse(
            {
                "success": False,
                "error": {
                    "code": "LOCAL_AUTH_MISMATCH",
                    "message": (
                        "本地账号密码与修茈市场账号不一致。"
                        "请使用与市场相同的密码，或联系管理员重置本地用户密码。"
                    ),
                },
            },
            status_code=_login_client_http_status(401),
        )

    if not exists:
        email = market_user_email_from_raw(market_result.get("raw"))
        blob = extract_market_user_blob(market_result)
        if not email and blob.get("email"):
            email = str(blob.get("email") or "").strip()
        pwd = password or secrets.token_urlsafe(24)
        if not jit_create_fn(username, pwd, email):
            return None, JSONResponse(
                {
                    "success": False,
                    "error": {
                        "code": "LOCAL_USER_CREATE_FAILED",
                        "message": "无法为本机创建与企业账号绑定的本地用户",
                    },
                },
                status_code=500,
            )

    if password:
        result = auth_app_service.login(username, password, enforce_mfa=False)
    else:
        result = auth_app_service.create_session_for_username(username)
    if not result.get("success"):
        return None, JSONResponse(result, status_code=_login_client_http_status(401))
    return result, None


def bind_tenant_for_login(
    *,
    user_id: int,
    company_brand: str,
    username: str,
) -> dict[str, Any]:
    """登录后绑定/创建租户，返回 tenant_id / tenant_name。"""
    out: dict[str, Any] = {"tenant_id": None, "tenant_name": ""}
    try:
        from app.application.tenant_subscription_app_service import (
            provision_trial_for_user,
            sync_tenant_display_name,
        )

        tid = provision_trial_for_user(
            user_id=user_id,
            username=username,
            display_name=company_brand or username,
        )
        if tid:
            out["tenant_id"] = int(tid)
        name = sync_tenant_display_name(user_id=int(user_id), company_brand=company_brand)
        if name:
            out["tenant_name"] = name
        elif company_brand:
            out["tenant_name"] = company_brand
    except RECOVERABLE_ERRORS:
        logger.exception("bind_tenant_for_login failed user_id=%s", user_id)
    return out


def _derive_and_heal_account_kind(
    *,
    user_id: Any,
    market_is_admin: bool,
    market_is_enterprise: bool,
    fallback: AccountKind,
) -> AccountKind:
    """从本地 User.tier 派生 account_kind；市场身份可向上提升并回写 User.tier（不下调）。"""
    from app.application.session_account_meta import derive_account_kind_from_user

    if user_id is None:
        return derive_account_kind_from_user(
            tier=fallback,
            market_is_admin=market_is_admin,
            market_is_enterprise=market_is_enterprise,
        )
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.get(User, int(user_id))
            tier = str(getattr(user, "tier", "") or "").strip() if user else ""
            kind = derive_account_kind_from_user(
                tier=tier,
                market_is_admin=market_is_admin,
                market_is_enterprise=market_is_enterprise,
            )
            if user is not None and kind in ("admin", "enterprise") and tier in ("", "personal"):
                user.tier = kind
                db.commit()
            return kind
    except RECOVERABLE_ERRORS:
        logger.exception("_derive_and_heal_account_kind failed user_id=%s", user_id)
        return derive_account_kind_from_user(
            tier=fallback,
            market_is_admin=market_is_admin,
            market_is_enterprise=market_is_enterprise,
        )


async def finalize_enterprise_login(
    *,
    result: dict[str, Any],
    session_id: str | None,
    market_result: dict[str, Any] | None,
    account_kind: AccountKind,
    username: str,
    sku: str,
    skip_market_sync: bool = False,
) -> dict[str, Any]:
    """绑定市场 token、会话元数据、Mod 权益与租户信息。"""
    from app.fastapi_routes.market_account import (
        fetch_market_membership_tier,
        save_session_market_token,
    )

    if not session_id:
        return result

    password_for_market = None
    try:
        if skip_market_sync:
            market_result = market_result or {"success": False}
        elif market_result is None and sku != "enterprise":
            password_for_market = True
        elif market_result is None:
            market_result = {"success": False}

        if password_for_market and isinstance(result, dict):
            pass

        mtok = str((market_result or {}).get("token") or "").strip()
        mrefresh = str((market_result or {}).get("refresh_token") or "").strip()
        if market_result and market_result.get("success") and mtok:
            save_session_market_token(str(session_id), mtok, mrefresh or None)
            result["market_access_token"] = mtok
            if mrefresh:
                result["market_refresh_token"] = mrefresh

        if market_result and market_result.get("success"):
            user_blob = extract_market_user_blob(market_result)
            market_uid: int | None = None
            if user_blob.get("id") is not None:
                market_uid = int(user_blob["id"])
            company_brand = company_brand_from_user_blob(user_blob)
            tenant_id_val: int | None = None
            tenant_name = company_brand
            user_id = (result.get("user") or {}).get("id")
            if user_id is not None:
                tenant_info = bind_tenant_for_login(
                    user_id=int(user_id),
                    company_brand=company_brand,
                    username=username,
                )
                if tenant_info.get("tenant_id") is not None:
                    tenant_id_val = int(tenant_info["tenant_id"])
                    result["tenant_id"] = tenant_id_val
                if tenant_info.get("tenant_name"):
                    tenant_name = str(tenant_info["tenant_name"])
                    result["tenant_name"] = tenant_name
            market_is_admin = bool(market_result.get("is_market_admin"))
            market_is_enterprise = bool(market_result.get("is_enterprise"))
            # 单一真相源 + 自动派生：account_kind 由本地 User.tier 派生（市场身份可向上提升），
            # 不再采用登录入口传入的 account_kind。
            account_kind = _derive_and_heal_account_kind(
                user_id=user_id,
                market_is_admin=market_is_admin,
                market_is_enterprise=market_is_enterprise,
                fallback=account_kind,
            )
            persist_session_account_meta(
                str(session_id),
                account_kind=account_kind,
                company_brand=company_brand,
                market_user_id=market_uid,
                market_is_admin=market_is_admin,
                market_is_enterprise=market_is_enterprise,
                tenant_id=tenant_id_val,
            )
            result["account_kind"] = account_kind
            result["company_brand"] = company_brand
            result["market_is_admin"] = market_is_admin
            result["market_is_enterprise"] = market_is_enterprise
            # 维度3 会员体系：登录后从市场同步会员等级到 Session.market_membership_tier
            if mtok:
                from app.application.session_account_meta import (
                    persist_session_membership_tier,
                )

                membership_tier = await fetch_market_membership_tier(mtok)
                if membership_tier:
                    persist_session_membership_tier(str(session_id), membership_tier)
                    result["market_membership_tier"] = membership_tier
        elif skip_market_sync:
            user_id = (result.get("user") or {}).get("id")
            if user_id is not None:
                tenant_info = bind_tenant_for_login(
                    user_id=int(user_id),
                    company_brand=str(result.get("company_brand") or username),
                    username=username,
                )
                if tenant_info.get("tenant_id") is not None:
                    result["tenant_id"] = tenant_info["tenant_id"]
                if tenant_info.get("tenant_name"):
                    result["tenant_name"] = tenant_info["tenant_name"]
                persist_session_account_meta(
                    str(session_id),
                    account_kind=account_kind,
                    company_brand=str(result.get("company_brand") or ""),
                    tenant_id=(
                        int(tenant_info["tenant_id"]) if tenant_info.get("tenant_id") else None
                    ),
                )
            result["account_kind"] = account_kind

        if sku == "enterprise" and market_result and market_result.get("success") and mtok:
            from app.enterprise.mod_entitlements import (
                get_cached_entitled_client_mod_ids,
                persist_entitlements_to_session_row,
                refresh_session_entitlements_from_market,
                reload_enterprise_mods_after_login,
            )

            market_uid = None
            raw_login = market_result.get("raw")
            if isinstance(raw_login, dict):
                ub = raw_login.get("user")
                if isinstance(ub, dict) and ub.get("id") is not None:
                    market_uid = int(ub["id"])
            client_ids = await refresh_session_entitlements_from_market(
                market_token=mtok,
                market_user_id=market_uid,
                market_username=username,
                session_id=str(session_id),
            )
            persist_entitlements_to_session_row(str(session_id), client_ids)
            await reload_enterprise_mods_after_login()
            cached = get_cached_entitled_client_mod_ids()
            if cached is not None:
                result["entitled_mod_ids"] = sorted(cached)

        if market_result:
            result["market_account"] = {
                "success": bool(market_result.get("success")),
                "market_base_url": market_result.get("market_base_url"),
                "message": market_result.get("message", ""),
                "is_enterprise": bool(market_result.get("is_enterprise")),
                "is_market_admin": bool(market_result.get("is_market_admin")),
            }
    except RECOVERABLE_ERRORS as exc:
        result["market_account"] = {
            "success": False,
            "message": f"市场账号自动同步失败：{exc}",
        }

    if session_id and "entitled_mod_ids" not in result:
        try:
            from app.enterprise.account_mod_binding import (
                augment_entitled_client_mod_ids_for_username,
            )
            from app.enterprise.mod_entitlements import (
                enterprise_mod_filter_active,
                get_cached_entitled_client_mod_ids,
                persist_entitlements_to_session_row,
                reload_enterprise_mods_after_login,
                set_session_entitlements,
            )

            fallback = augment_entitled_client_mod_ids_for_username(username, set())
            if fallback:
                set_session_entitlements(
                    market_user_id=None,
                    market_username=username,
                    entitled_client_mod_ids=fallback,
                )
                persist_entitlements_to_session_row(str(session_id), fallback)
                if enterprise_mod_filter_active():
                    await reload_enterprise_mods_after_login()
                cached = get_cached_entitled_client_mod_ids()
                if cached:
                    result["entitled_mod_ids"] = sorted(cached)
        except RECOVERABLE_ERRORS:
            logger.exception("account_mod_binding fallback on login failed")

    return result


async def run_market_first_login(
    *,
    username: str,
    password: str | None,
    account_kind: AccountKind,
    market_result: dict[str, Any] | None,
    auth_app_service: Any,
    sku: str,
    jit_create_fn: Any,
    market_user_email_from_raw: Any,
    login_market_fn: Any | None = None,
    totp_code: str | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """企业 SKU：市场先行，再本地 session + finalize。"""
    from app.application.session_account_meta import persist_session_account_meta

    login_username = username
    if sku == "enterprise":
        if market_result is None and login_market_fn and password:
            logger.info(
                "enterprise market-first login start username=%s account_kind=%s sku=%s",
                username,
                account_kind,
                sku,
            )
            market_result = await login_market_fn(username, password)
            logger.info(
                "enterprise market-first login result username=%s success=%s is_enterprise=%s is_market_admin=%s base=%s",
                username,
                bool((market_result or {}).get("success")),
                bool((market_result or {}).get("is_enterprise")),
                bool((market_result or {}).get("is_market_admin")),
                (market_result or {}).get("market_base_url"),
            )
        if not (market_result or {}).get("success"):
            if account_kind == "admin" and password:
                # 市场不可达的本地管理员应急登录：不阻断于本地 MFA
                local_admin = auth_app_service.login(username, password, enforce_mfa=False)
                user_role = str((local_admin.get("user") or {}).get("role") or "")
                if local_admin.get("success") and user_role == "admin":
                    session_id = local_admin.get("session_id")
                    if session_id:
                        # 复用 finalize 补充租户绑定 + 本地 mod 权益 fallback
                        local_admin = await finalize_enterprise_login(
                            result=local_admin,
                            session_id=str(session_id),
                            market_result=market_result,
                            account_kind=account_kind,
                            username=login_username,
                            sku=sku,
                            skip_market_sync=True,
                        )
                        # finalize skip_market_sync 分支不写 market_is_admin/market_is_enterprise，此处补充
                        # enterprise SKU 管理员默认拥有企业版权益（市场不可达时）
                        persist_session_account_meta(
                            str(session_id),
                            account_kind="admin",
                            company_brand=str(local_admin.get("company_brand") or ""),
                            market_user_id=None,
                            market_is_admin=True,
                            market_is_enterprise=True,
                            tenant_id=(
                                int(local_admin["tenant_id"])
                                if local_admin.get("tenant_id")
                                else None
                            ),
                        )
                    local_admin["account_kind"] = "admin"
                    local_admin["market_is_admin"] = True
                    local_admin["market_is_enterprise"] = True
                    local_admin["market_account"] = {
                        "success": False,
                        "market_base_url": (market_result or {}).get("market_base_url"),
                        "message": str(
                            (market_result or {}).get("message")
                            or "市场不可达，已使用本地管理员会话"
                        ),
                    }
                    return local_admin, None
            return None, market_auth_error_response(market_result or {})
        kind_err = validate_account_kind_for_market(
            account_kind,
            is_enterprise=bool((market_result or {}).get("is_enterprise")),
            is_market_admin=bool((market_result or {}).get("is_market_admin")),
        )
        if kind_err:
            logger.warning(
                "enterprise market-first account kind rejected username=%s account_kind=%s is_enterprise=%s is_market_admin=%s message=%s",
                username,
                account_kind,
                bool((market_result or {}).get("is_enterprise")),
                bool((market_result or {}).get("is_market_admin")),
                kind_err,
            )
            return None, JSONResponse(
                {
                    "success": False,
                    "message": kind_err,
                    "error": {
                        "code": "ACCOUNT_KIND_MISMATCH",
                        "message": kind_err,
                    },
                    "market_account": {
                        "success": True,
                        "market_base_url": (market_result or {}).get("market_base_url"),
                        "is_enterprise": bool((market_result or {}).get("is_enterprise")),
                        "is_market_admin": bool((market_result or {}).get("is_market_admin")),
                    },
                },
                status_code=_login_client_http_status(403),
            )
        login_username = username or resolve_market_username(market_result or {})
        if not login_username:
            return None, JSONResponse(
                {
                    "success": False,
                    "error": {"code": "INVALID_INPUT", "message": "市场未返回可用用户名"},
                },
                status_code=502,
            )
        result, err = await ensure_local_user_after_market(
            username=login_username,
            password=password,
            market_result=market_result or {},
            auth_app_service=auth_app_service,
            jit_create_fn=jit_create_fn,
            market_user_email_from_raw=market_user_email_from_raw,
        )
        if err:
            return None, err
    else:
        if not password:
            return None, JSONResponse(
                {"success": False, "error": {"code": "INVALID_INPUT", "message": "密码不能为空"}},
                status_code=_login_client_http_status(400),
            )
        # 通用 SKU 本地直登：强制 MFA（用户开启时），透传 TOTP
        result = auth_app_service.login(username, password, totp_code=totp_code)
        if not result.get("success"):
            return None, JSONResponse(result, status_code=_login_client_http_status(401))
        if market_result is None and login_market_fn:
            market_result = await login_market_fn(username, password)

    session_id = result.get("session_id") if result else None
    if result:
        result = await finalize_enterprise_login(
            result=result,
            session_id=str(session_id) if session_id else None,
            market_result=market_result,
            account_kind=account_kind,
            username=login_username,
            sku=sku,
        )
    return result, None


async def finalize_auth_after_oidc(
    *,
    auth_result: dict[str, Any],
    oidc_profile: dict[str, Any],
    oidc_access_token: str = "",
    account_kind: AccountKind,
    sku: str,
) -> dict[str, Any]:
    """OIDC 本地会话创建后，自动桥接 MODstore JWT 并走统一 finalize。"""
    from app.fastapi_routes.market_account import login_market_for_oidc_profile

    username = str((auth_result.get("user") or {}).get("username") or "")
    session_id = auth_result.get("session_id")
    market_result = await login_market_for_oidc_profile(
        oidc_profile,
        oidc_access_token=oidc_access_token,
    )
    if sku == "enterprise" and market_result.get("success"):
        kind_err = validate_account_kind_for_market(
            account_kind,
            is_enterprise=bool(market_result.get("is_enterprise")),
            is_market_admin=bool(market_result.get("is_market_admin")),
        )
        if kind_err:
            market_result = {
                "success": False,
                "message": kind_err,
                "market_base_url": market_result.get("market_base_url"),
            }
    return await finalize_enterprise_login(
        result=auth_result,
        session_id=str(session_id) if session_id else None,
        market_result=market_result,
        account_kind=account_kind,
        username=username,
        sku=sku,
        skip_market_sync=not bool(market_result.get("success")),
    )
