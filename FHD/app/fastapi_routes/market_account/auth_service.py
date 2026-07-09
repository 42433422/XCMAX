"""Market authentication services."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from fastapi.responses import JSONResponse

import app.fastapi_routes.market_account._patch as _p
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

def _token_from_auth_response(payload: Any) -> str:
    """Extract access JWT from market ``POST /api/auth/login`` JSON (several response shapes)."""
    if not isinstance(payload, dict):
        return ""
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else None
    candidates: list[Any] = []
    if inner:
        candidates.extend(
            [
                inner.get("access_token"),
                inner.get("token"),
                inner.get("market_access_token"),
            ]
        )
        nested = inner.get("tokens") if isinstance(inner.get("tokens"), dict) else None
        if nested:
            candidates.extend([nested.get("access_token"), nested.get("accessToken")])
    candidates.extend(
        [
            payload.get("access_token"),
            payload.get("token"),
            payload.get("market_access_token"),
        ]
    )
    nested_top = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else None
    if nested_top:
        candidates.extend([nested_top.get("access_token"), nested_top.get("accessToken")])
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""
def _refresh_token_from_auth_response(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    inner = payload.get("data") if isinstance(payload.get("data"), dict) else None
    candidates: list[Any] = []
    if inner:
        candidates.extend([inner.get("refresh_token"), inner.get("refreshToken")])
        nested = inner.get("tokens") if isinstance(inner.get("tokens"), dict) else None
        if nested:
            candidates.extend([nested.get("refresh_token"), nested.get("refreshToken")])
    candidates.extend([payload.get("refresh_token"), payload.get("refreshToken")])
    nested_top = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else None
    if nested_top:
        candidates.extend([nested_top.get("refresh_token"), nested_top.get("refreshToken")])
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s
    return ""
def _user_blob_from_market_payload(payload: Any) -> dict[str, Any]:
    """从市场 login/me 等多种 JSON 形态提取 user 字典。"""
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("user"), dict):
        return dict(payload["user"])
    data = payload.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("user"), dict):
            return dict(data["user"])
        if data.get("id") is not None and data.get("username"):
            return dict(data)
    if payload.get("id") is not None and payload.get("username"):
        return dict(payload)
    return {}
def _truthy_identity_flag(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(raw)
def _market_identity_from_payloads(*payloads: Any) -> tuple[bool, bool, dict[str, Any]]:
    """合并 login + /me 响应，得到 (is_enterprise, is_market_admin, user_blob)。"""
    is_enterprise = False
    is_market_admin = False
    user_blob: dict[str, Any] = {}
    for payload in payloads:
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            continue
        blob = _user_blob_from_market_payload(payload)
        if not blob:
            continue
        if not user_blob:
            user_blob = blob
        sources: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            sources.append(payload)
            data = payload.get("data")
            if isinstance(data, dict):
                sources.append(data)
        sources.append(blob)
        for source in sources:
            tier = str(source.get("tier") or "").strip().lower()
            account_kind = (
                str(source.get("account_kind") or source.get("accountKind") or "").strip().lower()
            )
            role = str(source.get("role") or "").strip().lower()
            if _truthy_identity_flag(source.get("is_enterprise")) or _truthy_identity_flag(
                source.get("market_is_enterprise")
            ):
                is_enterprise = True
            if tier == "enterprise" or account_kind == "enterprise":
                is_enterprise = True
            if _truthy_identity_flag(source.get("is_admin")) or _truthy_identity_flag(
                source.get("market_is_admin")
            ):
                is_market_admin = True
            if tier == "admin" or account_kind in {"admin", "admin_portal"}:
                is_market_admin = True
            if role in {"admin", "super_admin", "owner"}:
                is_market_admin = True
    return is_enterprise, is_market_admin, user_blob
def _market_user_id_from_auth_payload(payload: Any) -> int | None:
    """Extract a positive market user id from login/register response shapes."""
    candidates: list[Any] = []
    blob = _user_blob_from_market_payload(payload)
    if blob:
        candidates.extend([blob.get("id"), blob.get("user_id"), blob.get("market_user_id")])
    if isinstance(payload, dict):
        candidates.extend(
            [payload.get("id"), payload.get("user_id"), payload.get("market_user_id")]
        )
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend([data.get("id"), data.get("user_id"), data.get("market_user_id")])
            user = data.get("user")
            if isinstance(user, dict):
                candidates.extend([user.get("id"), user.get("user_id"), user.get("market_user_id")])
    for raw in candidates:
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            uid = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if uid > 0:
            return uid
    return None
async def refresh_session_market_token(session_id: str) -> str:
    """Use persisted modstore refresh_token to obtain a new access_token."""
    sid = (session_id or "").strip()
    if not sid:
        return ""
    refresh = _p.session_market_refresh_token(sid)
    if not refresh:
        return ""
    payload = await _p._proxy_json(
        "POST",
        "/api/auth/refresh",
        json_body={"refresh_token": refresh},
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return ""
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return ""
    access = _token_from_auth_response(payload)
    new_refresh = _refresh_token_from_auth_response(payload) or refresh
    if access and sid:
        _p.save_session_market_token(sid, access, new_refresh)
    return access
async def resolve_valid_market_access_token(session_id: str) -> str:
    """Return a working market access token, refreshing when /api/auth/me returns 401."""
    from app.application.surface_audit_demo_account import is_local_demo_market_token

    sid = (session_id or "").strip()
    # 多用户环境：从 session_id 反查 user_id，防止 fallback 串号
    user_id = _p._user_id_from_session(sid)
    tok = _p._normalize_bearer_token(_p.session_market_token(sid))
    if not tok and user_id is not None:
        tok = _p._normalize_bearer_token(_p.latest_session_market_token(user_id=user_id))
    if not tok:
        return ""
    if is_local_demo_market_token(tok):
        return tok
    me = await _p._proxy_json(
        "GET", "/api/auth/me", authorization=f"Bearer {tok}", return_error_payload=True
    )
    if isinstance(me, JSONResponse):
        logger.warning(
            "market unreachable during token validation (session_id=%s), using local token",
            sid[:8] if sid else "",
        )
        return tok
    if isinstance(me, dict) and me.get("__proxy_error__"):
        if _p._proxy_error_http_status(me) == 401:
            refreshed = await _p.refresh_session_market_token(sid)
            return _p._normalize_bearer_token(refreshed)
        logger.warning(
            "market /api/auth/me error status=%s, using local token",
            me.get("status_code"),
        )
        return tok
    return tok
def _looks_like_verification_required(payload: Any) -> bool:
    msg = _p._error_message(payload, 400)
    return bool(re.search(r"验证码|verification|code", msg, re.I))
async def _register_without_verification(username: str, password: str, email: str):
    """Use the server-side open registration API when the normal market form requires email code."""
    payload = await _p._proxy_json(
        "POST",
        "/api/market/open/register",
        json_body={"username": username, "password": password, "email": email},
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        payload = await _p._proxy_json(
            "POST",
            "/api/auth/register-open",
            json_body={"username": username, "password": password, "email": email},
            return_error_payload=True,
        )
    return payload
async def send_market_reset_password_code(email: str) -> dict[str, Any]:
    """Request password-reset verification email from the configured market server."""
    email_norm = (email or "").strip().lower()
    if not email_norm or "@" not in email_norm:
        return {"success": False, "message": "请填写有效邮箱"}
    payload = await _p._proxy_json(
        "POST",
        "/api/auth/send-reset-password-code",
        json_body={"email": email_norm},
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return {"success": False, "message": "市场服务不可用"}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _p._error_message(raw, status_code) or "无法连接修茈市场发送验证码",
            "market_base_url": _p._market_base_url(),
        }
    msg = ""
    if isinstance(payload, dict):
        msg = str(payload.get("message") or "").strip()
    return {
        "success": True,
        "message": msg or "若该邮箱已注册，将收到验证码邮件",
        "market_base_url": _p._market_base_url(),
        "raw": payload,
    }
async def reset_market_password_with_code(
    email: str, code: str, new_password: str
) -> dict[str, Any]:
    """Reset password on market server using email verification code."""
    email_norm = (email or "").strip().lower()
    code_s = (code or "").strip()
    if not email_norm or "@" not in email_norm:
        return {"success": False, "message": "请填写有效邮箱"}
    if len(code_s) < 4:
        return {"success": False, "message": "请填写验证码"}
    if len(new_password or "") < 6:
        return {"success": False, "message": "新密码至少 6 个字符"}
    payload = await _p._proxy_json(
        "POST",
        "/api/auth/reset-password",
        json_body={"email": email_norm, "code": code_s, "new_password": new_password},
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return {"success": False, "message": "市场服务不可用"}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 400)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _p._error_message(raw, status_code) or "重置失败",
            "raw": raw,
        }
    if isinstance(payload, dict) and payload.get("success") is False:
        return {
            "success": False,
            "message": str(payload.get("message") or payload.get("detail") or "重置失败"),
            "raw": payload,
        }
    return {
        "success": True,
        "message": "密码已重置",
        "raw": payload,
    }
async def register_market_user(
    username: str,
    password: str,
    email: str,
    verification_code: str = "",
) -> dict[str, Any]:
    """Register on the configured Xiuci market server. Returns success/message/token/raw."""
    register_body = {
        "username": username,
        "password": password,
        "email": email,
        "verification_code": (verification_code or "").strip() or "000000",
    }
    payload = await _p._proxy_json(
        "POST", "/api/auth/register", json_body=register_body, return_error_payload=True
    )
    if isinstance(payload, JSONResponse):
        return {"success": False, "message": "市场服务不可用"}
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 400)
        raw_error = payload.get("payload")
        if not verification_code and _looks_like_verification_required(raw_error):
            payload = await _p._register_without_verification(username, password, email)
            if isinstance(payload, dict) and payload.get("__proxy_error__"):
                status_code = int(payload.get("status_code") or 400)
                raw_error = payload.get("payload")
            else:
                status_code = 200
        if status_code >= 400:
            return {
                "success": False,
                "message": _p._error_message(raw_error, status_code),
                "raw": raw_error,
            }
    token = _token_from_auth_response(payload)
    refresh = _refresh_token_from_auth_response(payload)
    return {
        "success": True,
        "message": "",
        "token": token,
        "refresh_token": refresh,
        "market_user_id": _market_user_id_from_auth_payload(payload),
        "raw": payload,
        "market_base_url": _p._market_base_url(),
    }
def _is_local_market_base(url: str) -> bool:
    host = (url or "").strip().lower()
    return "127.0.0.1" in host or "localhost" in host
def _demo_market_login_payload(shim: dict[str, Any], *, market_base_url: str) -> dict[str, Any]:
    raw_out = dict(shim.get("raw") or {})
    if not isinstance(raw_out.get("user"), dict):
        raw_out["user"] = {
            "id": int((shim.get("raw") or {}).get("user", {}).get("id") or 900001),
            "username": str((shim.get("raw") or {}).get("user", {}).get("username") or ""),
            "is_enterprise": True,
            "is_admin": False,
        }
    return {
        "success": True,
        "market_base_url": market_base_url,
        "token": str(shim.get("token") or "").strip(),
        "refresh_token": str(shim.get("refresh_token") or "").strip(),
        "is_enterprise": bool(shim.get("is_enterprise")),
        "is_market_admin": bool(shim.get("is_market_admin")),
        "raw": raw_out,
    }
async def _normalize_market_auth_payload(
    payload: Any,
    *,
    market_base: str | None = None,
) -> dict[str, Any]:
    """Turn market login JSON into normalized token payload."""
    if isinstance(payload, JSONResponse):
        try:
            raw_body = json.loads(payload.body.decode("utf-8") if payload.body else "{}")
        except RECOVERABLE_ERRORS:
            raw_body = {}
        status_code = int(payload.status_code or 502)
        message = (
            str(raw_body.get("message") or "").strip()
            or str(raw_body.get("detail") or "").strip()
            or _p._error_message(raw_body, status_code)
        )
        err = raw_body.get("error") if isinstance(raw_body.get("error"), dict) else {}
        code = str(err.get("code") or "").strip()
        if status_code >= 500 and not code:
            code = "MARKET_AUTH_UNAVAILABLE"
        return {
            "success": False,
            "message": message,
            "status_code": status_code,
            "error_code": code
            or ("MARKET_AUTH_UNAVAILABLE" if status_code >= 500 else "MARKET_AUTH_FAILED"),
            "raw": raw_body,
            "market_base_url": market_base or _p._market_base_url(),
        }
    token = _token_from_auth_response(payload)
    refresh = _refresh_token_from_auth_response(payload)
    if not token:
        return {"success": False, "message": "市场登录成功但未返回 access_token", "raw": payload}
    me = await _p._proxy_json(
        "GET", "/api/auth/me", authorization=f"Bearer {token}", return_error_payload=True
    )
    is_enterprise, is_market_admin, user_blob = _market_identity_from_payloads(payload, me)
    logger.info(
        "market auth normalized base=%s success=True is_enterprise=%s is_market_admin=%s username=%s raw_keys=%s me_keys=%s",
        market_base or _p._market_base_url(),
        is_enterprise,
        is_market_admin,
        str(user_blob.get("username") or ""),
        sorted(payload.keys()) if isinstance(payload, dict) else [],
        sorted(me.keys()) if isinstance(me, dict) else [],
    )
    raw_out = dict(payload) if isinstance(payload, dict) else {}
    if user_blob and not isinstance(raw_out.get("user"), dict):
        raw_out["user"] = user_blob
    return {
        "success": True,
        "market_base_url": market_base or _p._market_base_url(),
        "token": token,
        "refresh_token": refresh,
        "is_enterprise": is_enterprise,
        "is_market_admin": is_market_admin,
        "raw": raw_out,
    }
async def login_market_with_password(username: str, password: str) -> dict[str, Any]:
    """Authenticate against the market server and return a normalized token payload."""
    from app.application.surface_audit_demo_account import try_local_demo_market_login

    market_base = _p._market_base_url()
    demo_shim = try_local_demo_market_login(username, password)
    if demo_shim and _p._is_local_market_base(market_base):
        return _p._demo_market_login_payload(demo_shim, market_base_url=market_base)

    payload = await _p._proxy_json(
        "POST", "/api/auth/login", json_body={"username": username, "password": password}
    )
    if isinstance(payload, JSONResponse):
        try:
            status_code = int(payload.status_code or 502)
        except (TypeError, ValueError):
            status_code = 502
        if demo_shim and _p._is_local_market_base(market_base) and status_code >= 400:
            return _p._demo_market_login_payload(demo_shim, market_base_url=market_base)
    result = await _p._normalize_market_auth_payload(payload, market_base=market_base)
    if not result.get("success") and demo_shim and _p._is_local_market_base(market_base):
        sc = int(result.get("status_code") or 502)
        if sc >= 400:
            return _p._demo_market_login_payload(demo_shim, market_base_url=market_base)
    return result
async def login_market_with_phone_code(phone: str, code: str) -> dict[str, Any]:
    """Authenticate against market via phone verification code."""
    market_base = _p._market_base_url()
    payload = await _p._proxy_json(
        "POST",
        "/api/auth/login-with-phone-code",
        json_body={"phone": (phone or "").strip(), "code": (code or "").strip()},
    )
    return await _p._normalize_market_auth_payload(payload, market_base=market_base)
def _market_internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
async def ensure_market_enterprise_profile(
    market_user_id: int | str | None,
    *,
    username: str = "",
    company: str = "",
    mod_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Mark a registered market account as enterprise through the internal market API."""
    try:
        uid = int(str(market_user_id or "").strip())
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        return {
            "success": False,
            "message": "修茈市场注册成功但未返回用户ID，无法标记企业账号",
            "market_base_url": _p._market_base_url(),
        }
    internal_key = _p._market_internal_api_key()
    if not internal_key:
        return {
            "success": False,
            "message": "未配置 XCAGI_MARKET_INTERNAL_API_KEY，无法标记市场企业账号",
            "market_base_url": _p._market_base_url(),
        }
    body: dict[str, Any] = {
        "market_user_id": uid,
        "company": (company or "").strip(),
        "display_name": (username or "").strip(),
    }
    requested_mod_ids = _dedupe_mod_ids([str(x) for x in (mod_ids or [])])
    if requested_mod_ids:
        body["mod_ids"] = requested_mod_ids
    payload = await _p._proxy_json(
        "POST",
        "/api/internal/cs-intake/ensure-enterprise-profile",
        json_body=body,
        extra_headers={"X-Internal-Api-Key": internal_key},
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return {
            "success": False,
            "message": "市场服务不可用，无法标记企业账号",
            "status_code": int(getattr(payload, "status_code", 502) or 502),
            "market_base_url": _p._market_base_url(),
        }
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _p._error_message(raw, status_code) or "市场企业标记失败",
            "status_code": status_code,
            "raw": raw,
            "market_base_url": _p._market_base_url(),
        }
    if not isinstance(payload, dict):
        return {
            "success": False,
            "message": "市场企业标记返回格式异常",
            "raw": payload,
            "market_base_url": _p._market_base_url(),
        }
    is_enterprise = _truthy_identity_flag(payload.get("is_enterprise")) or _truthy_identity_flag(
        payload.get("market_is_enterprise")
    )
    if not (payload.get("ok") or payload.get("success")) or not is_enterprise:
        return {
            "success": False,
            "message": str(payload.get("message") or payload.get("detail") or "市场企业标记失败"),
            "raw": payload,
            "market_base_url": _p._market_base_url(),
        }
    return {
        "success": True,
        "market_user_id": uid,
        "username": str(payload.get("username") or username or "").strip(),
        "is_enterprise": True,
        "mod_ids": [
            str(x).strip()
            for x in (payload.get("mod_ids") or requested_mod_ids)
            if str(x or "").strip()
        ],
        "added_mod_ids": [
            str(x).strip() for x in (payload.get("added_mod_ids") or []) if str(x or "").strip()
        ],
        "raw": payload,
        "market_base_url": _p._market_base_url(),
    }
def _dedupe_mod_ids(mod_ids: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in mod_ids:
        mid = str(raw or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out
def enterprise_mod_ids_for_industry(industry_id: str) -> list[str]:
    """Resolve the MODstore entitlements implied by a selected industry."""
    iid = str(industry_id or "").strip()
    if not iid:
        return []
    mod_ids: list[str] = []
    try:
        from app.mod_sdk.industry_seed import industry_mod_id_for

        mid = str(industry_mod_id_for(iid) or "").strip()
        if mid:
            mod_ids.append(mid)
    except RECOVERABLE_ERRORS:
        logger.exception("enterprise_mod_ids_for_industry: industry_seed failed industry=%s", iid)
    try:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id_for_industry

        mid = str(canonical_mod_id_for_industry(iid) or "").strip()
        if mid:
            mod_ids.append(mid)
    except RECOVERABLE_ERRORS:
        logger.exception("enterprise_mod_ids_for_industry: alias failed industry=%s", iid)
    try:
        from app.mod_sdk.customer_delivery import deliveries_for_industry

        for row in deliveries_for_industry(iid):
            if not isinstance(row, dict):
                continue
            mid = str(row.get("industry_mod_id") or "").strip()
            if mid:
                mod_ids.append(mid)
    except RECOVERABLE_ERRORS:
        logger.exception("enterprise_mod_ids_for_industry: delivery failed industry=%s", iid)
    return _dedupe_mod_ids(mod_ids)
async def grant_market_enterprise_entitlements_for_session(
    session_id: str,
    industry_id: str,
) -> dict[str, Any]:
    """Grant selected-industry MODstore entitlements for the current FHD session."""
    sid = str(session_id or "").strip()
    mod_ids = enterprise_mod_ids_for_industry(industry_id)
    if not mod_ids:
        return {"success": True, "mod_ids": [], "added_mod_ids": []}
    if not sid:
        return {"success": False, "message": "缺少登录会话，无法写入市场行业权限"}
    market_user_id: int | None = None
    try:
        from app.application.session_account_meta import load_session_account_meta

        meta = load_session_account_meta(sid) or {}
        raw_uid = meta.get("market_user_id")
        if raw_uid is not None:
            market_user_id = int(raw_uid)
    except (TypeError, ValueError):
        market_user_id = None
    except RECOVERABLE_ERRORS:
        logger.exception("grant_market_enterprise_entitlements: load session meta failed")
    if market_user_id is None:
        token = await _p.resolve_valid_market_access_token(sid)
        from app.enterprise.mod_entitlements import _market_user_id_from_access_token

        market_user_id = _market_user_id_from_access_token(token)
    if market_user_id is None:
        return {"success": False, "message": "当前会话没有市场用户ID，无法写入市场行业权限"}
    return await _p.ensure_market_enterprise_profile(
        market_user_id,
        mod_ids=mod_ids,
    )
def _oidc_identity_from_profile(profile: dict[str, Any]) -> tuple[str, str, str]:
    username = str(
        profile.get("preferred_username") or profile.get("email") or profile.get("sub") or ""
    ).strip()
    email = str(profile.get("email") or "").strip()
    oidc_sub = str(profile.get("sub") or "").strip()
    return username, email, oidc_sub
async def login_market_for_oidc_profile(
    profile: dict[str, Any],
    *,
    oidc_access_token: str = "",
) -> dict[str, Any]:
    """OIDC SSO 后自动签发/绑定 MODstore JWT（内部桥接；可选 IdP bearer 探测）。"""
    market_base = _p._market_base_url()
    username, email, oidc_sub = _oidc_identity_from_profile(profile or {})
    if not username and not email:
        return {
            "success": False,
            "message": "OIDC 未返回可用于市场同步的身份字段",
            "market_base_url": market_base,
        }

    oidc_tok = _p._normalize_bearer_token(oidc_access_token or "")
    if oidc_tok:
        me_payload = await _p._proxy_json(
            "GET",
            "/api/auth/me",
            authorization=f"Bearer {oidc_tok}",
            return_error_payload=True,
        )
        if isinstance(me_payload, dict) and not me_payload.get("__proxy_error__"):
            is_enterprise, is_market_admin, user_blob = _market_identity_from_payloads(
                me_payload, me_payload
            )
            raw_out: dict[str, Any] = dict(me_payload) if isinstance(me_payload, dict) else {}
            if user_blob and not isinstance(raw_out.get("user"), dict):
                raw_out["user"] = user_blob
            return {
                "success": True,
                "market_base_url": market_base,
                "token": oidc_tok,
                "refresh_token": "",
                "is_enterprise": is_enterprise,
                "is_market_admin": is_market_admin,
                "raw": raw_out,
            }

    internal_key = _p._market_internal_api_key()
    if not internal_key:
        return {
            "success": False,
            "message": ("未配置 XCAGI_MARKET_INTERNAL_API_KEY，SSO 会话无法自动绑定修茈市场 token"),
            "market_base_url": market_base,
        }

    payload = await _p._proxy_json(
        "POST",
        "/api/auth/internal/sso-issue-token",
        json_body={
            "username": username,
            "email": email,
            "oidc_sub": oidc_sub,
            "display_name": str(
                profile.get("name") or profile.get("given_name") or username
            ).strip()[:128],
        },
        extra_headers={"X-Internal-Api-Key": internal_key},
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        raw = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        msg = str(raw.get("detail") or raw.get("message") or "市场 SSO 桥接失败")
        return {
            "success": False,
            "message": msg,
            "status_code": int(payload.get("status_code") or 502),
            "market_base_url": market_base,
        }
    return await _p._normalize_market_auth_payload(payload, market_base=market_base)
async def send_market_phone_code(phone: str) -> dict[str, Any]:
    """Proxy send-phone-code to market."""
    payload = await _p._proxy_json(
        "POST",
        "/api/auth/send-phone-code",
        json_body={"phone": (phone or "").strip()},
    )
    if isinstance(payload, JSONResponse):
        try:
            raw_body = json.loads(payload.body.decode("utf-8") if payload.body else "{}")
        except RECOVERABLE_ERRORS:
            raw_body = {}
        return {
            "success": False,
            "message": str(raw_body.get("message") or raw_body.get("detail") or "发送验证码失败"),
            "status_code": int(payload.status_code or 502),
        }
    if isinstance(payload, dict):
        return {"success": True, "message": str(payload.get("message") or "验证码已发送")}
    return {"success": True, "message": "验证码已发送"}
