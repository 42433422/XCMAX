# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


async def login_market_with_password(username: str, password: str) -> dict[str, _facade().Any]:
    """Authenticate against the market server and return a normalized token payload."""
    from app.application.surface_audit_demo_account import try_local_demo_market_login

    market_base = _facade()._market_base_url()
    demo_shim = try_local_demo_market_login(username, password)
    if demo_shim and _facade()._is_local_market_base(market_base):
        return _facade()._demo_market_login_payload(demo_shim, market_base_url=market_base)
    payload = await _facade()._proxy_json(
        "POST", "/api/auth/login", json_body={"username": username, "password": password}
    )
    if isinstance(payload, _facade().JSONResponse):
        try:
            status_code = int(payload.status_code or 502)
        except (TypeError, ValueError):
            status_code = 502
        if demo_shim and _facade()._is_local_market_base(market_base) and (status_code >= 400):
            return _facade()._demo_market_login_payload(demo_shim, market_base_url=market_base)
    result = await _facade()._normalize_market_auth_payload(payload, market_base=market_base)
    if not result.get("success") and demo_shim and _facade()._is_local_market_base(market_base):
        sc = int(result.get("status_code") or 502)
        if sc >= 400:
            return _facade()._demo_market_login_payload(demo_shim, market_base_url=market_base)
    return result


async def login_market_with_phone_code(phone: str, code: str) -> dict[str, _facade().Any]:
    """Authenticate against market via phone verification code."""
    market_base = _facade()._market_base_url()
    payload = await _facade()._proxy_json(
        "POST",
        "/api/auth/login-with-phone-code",
        json_body={"phone": (phone or "").strip(), "code": (code or "").strip()},
    )
    return await _facade()._normalize_market_auth_payload(payload, market_base=market_base)


def _market_internal_api_key() -> str:
    return (
        _facade().os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or _facade().os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


async def ensure_market_enterprise_profile(
    market_user_id: int | str | None,
    *,
    username: str = "",
    company: str = "",
    mod_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, _facade().Any]:
    """Mark a registered market account as enterprise through the internal market API."""
    try:
        uid = int(str(market_user_id or "").strip())
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        return {
            "success": False,
            "message": "修茈市场注册成功但未返回用户ID，无法标记企业账号",
            "market_base_url": _facade()._market_base_url(),
        }
    internal_key = _facade()._market_internal_api_key()
    if not internal_key:
        return {
            "success": False,
            "message": "未配置 XCAGI_MARKET_INTERNAL_API_KEY，无法标记市场企业账号",
            "market_base_url": _facade()._market_base_url(),
        }
    body: dict[str, _facade().Any] = {
        "market_user_id": uid,
        "company": (company or "").strip(),
        "display_name": (username or "").strip(),
    }
    requested_mod_ids = _facade()._dedupe_mod_ids([str(x) for x in mod_ids or []])
    if requested_mod_ids:
        body["mod_ids"] = requested_mod_ids
    payload = await _facade()._proxy_json(
        "POST",
        "/api/internal/cs-intake/ensure-enterprise-profile",
        json_body=body,
        extra_headers={"X-Internal-Api-Key": internal_key},
        return_error_payload=True,
    )
    if isinstance(payload, _facade().JSONResponse):
        return {
            "success": False,
            "message": "市场服务不可用，无法标记企业账号",
            "status_code": int(getattr(payload, "status_code", 502) or 502),
            "market_base_url": _facade()._market_base_url(),
        }
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw = payload.get("payload")
        return {
            "success": False,
            "message": _facade()._error_message(raw, status_code) or "市场企业标记失败",
            "status_code": status_code,
            "raw": raw,
            "market_base_url": _facade()._market_base_url(),
        }
    if not isinstance(payload, dict):
        return {
            "success": False,
            "message": "市场企业标记返回格式异常",
            "raw": payload,
            "market_base_url": _facade()._market_base_url(),
        }
    is_enterprise = _facade()._truthy_identity_flag(
        payload.get("is_enterprise")
    ) or _facade()._truthy_identity_flag(payload.get("market_is_enterprise"))
    if not (payload.get("ok") or payload.get("success")) or not is_enterprise:
        return {
            "success": False,
            "message": str(payload.get("message") or payload.get("detail") or "市场企业标记失败"),
            "raw": payload,
            "market_base_url": _facade()._market_base_url(),
        }
    return {
        "success": True,
        "market_user_id": uid,
        "username": str(payload.get("username") or username or "").strip(),
        "is_enterprise": True,
        "mod_ids": [
            str(x).strip()
            for x in payload.get("mod_ids") or requested_mod_ids
            if str(x or "").strip()
        ],
        "added_mod_ids": [
            str(x).strip() for x in payload.get("added_mod_ids") or [] if str(x or "").strip()
        ],
        "raw": payload,
        "market_base_url": _facade()._market_base_url(),
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
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception(
            "enterprise_mod_ids_for_industry: industry_seed failed industry=%s", iid
        )
    try:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id_for_industry

        mid = str(canonical_mod_id_for_industry(iid) or "").strip()
        if mid:
            mod_ids.append(mid)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("enterprise_mod_ids_for_industry: alias failed industry=%s", iid)
    try:
        from app.mod_sdk.customer_delivery import deliveries_for_industry

        for row in deliveries_for_industry(iid):
            if not isinstance(row, dict):
                continue
            mid = str(row.get("industry_mod_id") or "").strip()
            if mid:
                mod_ids.append(mid)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception(
            "enterprise_mod_ids_for_industry: delivery failed industry=%s", iid
        )
    return _facade()._dedupe_mod_ids(mod_ids)


async def grant_market_enterprise_entitlements_for_session(
    session_id: str, industry_id: str
) -> dict[str, _facade().Any]:
    """Grant selected-industry MODstore entitlements for the current FHD session."""
    sid = str(session_id or "").strip()
    mod_ids = _facade().enterprise_mod_ids_for_industry(industry_id)
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
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("grant_market_enterprise_entitlements: load session meta failed")
    if market_user_id is None:
        token = await _facade().resolve_valid_market_access_token(sid)
        from app.enterprise.mod_entitlements import _market_user_id_from_access_token

        market_user_id = _market_user_id_from_access_token(token)
    if market_user_id is None:
        return {"success": False, "message": "当前会话没有市场用户ID，无法写入市场行业权限"}
    return await _facade().ensure_market_enterprise_profile(market_user_id, mod_ids=mod_ids)


def _oidc_identity_from_profile(profile: dict[str, _facade().Any]) -> tuple[str, str, str]:
    username = str(
        profile.get("preferred_username") or profile.get("email") or profile.get("sub") or ""
    ).strip()
    email = str(profile.get("email") or "").strip()
    oidc_sub = str(profile.get("sub") or "").strip()
    return (username, email, oidc_sub)


async def login_market_for_oidc_profile(
    profile: dict[str, _facade().Any], *, oidc_access_token: str = ""
) -> dict[str, _facade().Any]:
    """OIDC SSO 后自动签发/绑定 MODstore JWT（内部桥接；可选 IdP bearer 探测）。"""
    market_base = _facade()._market_base_url()
    username, email, oidc_sub = _facade()._oidc_identity_from_profile(profile or {})
    if not username and (not email):
        return {
            "success": False,
            "message": "OIDC 未返回可用于市场同步的身份字段",
            "market_base_url": market_base,
        }
    oidc_tok = _facade()._normalize_bearer_token(oidc_access_token or "")
    if oidc_tok:
        me_payload = await _facade()._proxy_json(
            "GET", "/api/auth/me", authorization=f"Bearer {oidc_tok}", return_error_payload=True
        )
        if isinstance(me_payload, dict) and (not me_payload.get("__proxy_error__")):
            is_enterprise, is_market_admin, user_blob = _facade()._market_identity_from_payloads(
                me_payload, me_payload
            )
            raw_out: dict[str, _facade().Any] = (
                dict(me_payload) if isinstance(me_payload, dict) else {}
            )
            if user_blob and (not isinstance(raw_out.get("user"), dict)):
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
    internal_key = _facade()._market_internal_api_key()
    if not internal_key:
        return {
            "success": False,
            "message": "未配置 XCAGI_MARKET_INTERNAL_API_KEY，SSO 会话无法自动绑定修茈市场 token",
            "market_base_url": market_base,
        }
    payload = await _facade()._proxy_json(
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
        if not isinstance(raw, dict):
            raw = {}
        msg = str(raw.get("detail") or raw.get("message") or "市场 SSO 桥接失败")
        return {
            "success": False,
            "message": msg,
            "status_code": int(payload.get("status_code") or 502),
            "market_base_url": market_base,
        }
    return await _facade()._normalize_market_auth_payload(payload, market_base=market_base)


async def send_market_phone_code(phone: str) -> dict[str, _facade().Any]:
    """Proxy send-phone-code to market."""
    payload = await _facade()._proxy_json(
        "POST", "/api/auth/send-phone-code", json_body={"phone": (phone or "").strip()}
    )
    if isinstance(payload, _facade().JSONResponse):
        try:
            raw_body = _facade().json.loads(
                bytes(payload.body).decode("utf-8") if payload.body else "{}"
            )
        except _facade().RECOVERABLE_ERRORS:
            raw_body = {}
        return {
            "success": False,
            "message": str(raw_body.get("message") or raw_body.get("detail") or "发送验证码失败"),
            "status_code": int(payload.status_code or 502),
        }
    if isinstance(payload, dict):
        return {"success": True, "message": str(payload.get("message") or "验证码已发送")}
    return {"success": True, "message": "验证码已发送"}


@_facade().router.post("/send-phone-code")
async def market_send_phone_code(
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    phone = str(body.get("phone") or "").strip()
    if not phone:
        return _facade().JSONResponse(
            {"success": False, "message": "请填写手机号"}, status_code=400
        )
    result = await _facade().send_market_phone_code(phone)
    if not result.get("success"):
        status = int(result.get("status_code") or 502)
        return _facade().JSONResponse(result, status_code=status if status >= 400 else 502)
    return {"success": True, "message": result.get("message") or "验证码已发送"}


@_facade().router.post("/send-register-code")
async def market_send_register_code(
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    result = await _facade().send_market_register_code(str(body.get("email") or ""))
    if not result.get("success"):
        status = int(result.get("status_code") or 502)
        return _facade().JSONResponse(result, status_code=status if status >= 400 else 502)
    return {"success": True, "message": result.get("message") or "验证码已发送"}
