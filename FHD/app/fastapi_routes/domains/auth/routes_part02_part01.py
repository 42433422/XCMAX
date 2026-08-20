# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.auth.routes")


@_facade().router.post("/api/auth/register")
async def auth_register(
    request: _facade().Request, body: dict = _facade().Body(default_factory=dict)
):
    """Register locally (PostgreSQL users) and optionally on Xiuci market; then create session."""
    from app.application import get_user_app_service
    from app.application.auth_app_service import get_auth_app_service
    from app.fastapi_routes.market_account import (
        login_market_with_password,
        register_market_user,
        save_session_market_token,
    )
    from app.mod_sdk.product_skus import resolve_product_sku

    username = (body.get("username") or "").strip()
    password = body.get("password", "")
    email = (body.get("email") or "").strip()
    verification_code = str(body.get("verification_code") or body.get("code") or "").strip()
    industry_id = (body.get("industry_id") or "").strip()
    budget_range = (body.get("budget_range") or "").strip()
    if not username or not password:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "用户名和密码不能为空"),
            status_code=400,
        )
    if len(password) < 6:
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().WEAK_PASSWORD, "密码至少 6 个字符"), status_code=400
        )
    sku = resolve_product_sku() or "generic"
    auth_app_service = get_auth_app_service()
    if sku == "enterprise":
        reg_email = email
        market_reg = await register_market_user(username, password, reg_email, verification_code)
        if not market_reg.get("success"):
            return _facade().JSONResponse(
                _facade().error_envelope(
                    _facade().MARKET_REGISTER_FAILED, market_reg.get("message", "修茈市场注册失败")
                ),
                status_code=400,
            )
        if not bool(market_reg.get("desktop_access")):
            payload = _facade().registration_response.pending_registration_payload(market_reg)
            return _facade().JSONResponse(payload)
        email_market = _facade()._market_user_email_from_raw(market_reg.get("raw")) or reg_email
        _facade()._jit_create_local_user_for_enterprise(username, password, email_market)
        result = auth_app_service.login(username, password)
        if not result.get("success"):
            return _facade().JSONResponse(
                _facade().error_envelope(
                    _facade().LOCAL_LOGIN_AFTER_REGISTER,
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
        result = _facade()._enrich_register_with_tenant(
            result=result,
            username=username,
            session_id=str(session_id) if session_id else None,
            sku=sku,
            company_brand=email_market or email,
        )
    else:
        if not _facade()._open_registration_allowed(sku):
            return _facade().JSONResponse(
                _facade().error_envelope(
                    _facade().REGISTRATION_DISABLED, "本部署未开放自助注册，请联系管理员创建账号"
                ),
                status_code=403,
            )
        user_service = get_user_app_service()
        created = user_service.create_user(
            username=username,
            password=password,
            display_name=body.get("display_name") or username,
            email=email,
            role="viewer",
        )
        if not created.get("success"):
            msg = created.get("message", "创建用户失败")
            if "已存在" in msg or "unique" in msg.lower():
                msg = "用户名已存在"
            return _facade().JSONResponse(
                _facade().error_envelope(_facade().CREATE_FAILED, msg), status_code=400
            )
        result = auth_app_service.login(username, password)
        if not result.get("success"):
            return _facade().JSONResponse(
                _facade().error_envelope(
                    _facade().LOGIN_AFTER_REGISTER, result.get("message", "注册成功但登录失败")
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
        except _facade().INFRA_TRANSIENT:
            _facade().logger.exception("optional market sync after local register failed")
        result = _facade()._enrich_register_with_tenant(
            result=result,
            username=username,
            session_id=str(session_id) if session_id else None,
            sku=sku,
            company_brand=email or username,
        )
    from app.application.account_registration import apply_account_profile_on_register

    apply_account_profile_on_register(
        username,
        tier="enterprise" if sku == "enterprise" else "personal",
        industry_id=industry_id,
        budget_range=budget_range,
    )
    payload = {"success": True, **result}
    return _facade()._attach_session_cookie(
        _facade().JSONResponse(payload), result.get("session_id")
    )


@_facade().router.post("/api/auth/login")
async def auth_login(request: _facade().Request, body: dict = _facade().Body(default_factory=dict)):
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
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "用户名和密码不能为空"),
            status_code=200,
        )
    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku() or "personal"
    account_kind = normalize_account_kind(
        body.get("account_kind"), default="enterprise" if sku == "enterprise" else "personal"
    )
    result, err = await run_market_first_login(
        username=username,
        password=password,
        account_kind=account_kind,
        market_result=None,
        auth_app_service=auth_app_service,
        sku=sku,
        jit_create_fn=_facade()._jit_create_local_user_for_enterprise,
        market_user_email_from_raw=_facade()._market_user_email_from_raw,
        login_market_fn=login_market_with_password,
        totp_code=str(body.get("totp_code") or "").strip() or None,
    )
    if err:
        auth_login_duration_seconds.labels(auth_method="password").observe(
            time.perf_counter() - login_start
        )
        return err
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
            except _facade().INFRA_TRANSIENT:
                _facade().logger.exception("issue web tokens failed")
    resp = _facade()._attach_session_cookie(
        _facade().JSONResponse(result or {}), (result or {}).get("session_id")
    )
    auth_login_duration_seconds.labels(auth_method="password").observe(
        time.perf_counter() - login_start
    )
    return resp


@_facade().router.post("/api/auth/login-with-phone-code")
async def auth_login_with_phone_code(
    request: _facade().Request, body: dict = _facade().Body(default_factory=dict)
):
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
        return _facade().JSONResponse(
            _facade().error_envelope(_facade().INVALID_INPUT, "手机号和验证码不能为空"),
            status_code=400,
        )
    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku() or "personal"
    account_kind = normalize_account_kind(
        body.get("account_kind"), default="enterprise" if sku == "enterprise" else "personal"
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
        jit_create_fn=_facade()._jit_create_local_user_for_enterprise,
        market_user_email_from_raw=_facade()._market_user_email_from_raw,
        login_market_fn=None,
    )
    if err:
        auth_login_duration_seconds.labels(auth_method="phone_code").observe(
            time.perf_counter() - login_start
        )
        return err
    resp = _facade()._attach_session_cookie(
        _facade().JSONResponse(result or {}), (result or {}).get("session_id")
    )
    auth_login_duration_seconds.labels(auth_method="phone_code").observe(
        time.perf_counter() - login_start
    )
    return resp


@_facade().router.get("/api/auth/oidc/status")
def auth_oidc_status():
    from app.infrastructure.auth.oidc_provider import oidc_enabled

    return {"success": True, "data": {"enabled": oidc_enabled()}}


@_facade().router.get("/api/auth/oidc/start")
async def auth_oidc_start(request: _facade().Request):
    from fastapi.responses import RedirectResponse

    from app.infrastructure.auth.oidc_provider import (
        build_authorize_url,
        oidc_enabled,
        sign_oidc_state,
    )

    if not oidc_enabled():
        return _facade().JSONResponse({"success": False, "message": "OIDC 未启用"}, status_code=404)
    return_to = str(request.query_params.get("return") or "").strip()
    state = sign_oidc_state(return_to=return_to)
    url = await build_authorize_url(state=state)
    return RedirectResponse(url=url, status_code=302)


@_facade().router.get("/api/auth/oidc/callback")
async def auth_oidc_callback(request: _facade().Request):
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
        raw_profile = oidc_session.get("profile")
        profile: dict[str, _facade().Any] = (
            dict(raw_profile) if isinstance(raw_profile, dict) else {}
        )
    except _facade().INFRA_TRANSIENT as exc:
        _facade().logger.exception("OIDC exchange failed")
        return RedirectResponse(
            url=f"{base}?oidc_error=OIDC_EXCHANGE&oidc_message={quote(str(exc))}", status_code=302
        )
    auth_app_service = get_auth_app_service()
    auth_result = auth_app_service.authenticate_oidc_user(profile)
    if not auth_result.get("success"):
        msg = str(auth_result.get("message") or "OIDC 登录失败")
        return RedirectResponse(
            url=f"{base}?oidc_error=OIDC_AUTH&oidc_message={quote(msg)}", status_code=302
        )
    sku = resolve_product_sku() or "personal"
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
    return _facade()._attach_session_cookie(resp, payload.get("session_id"))
