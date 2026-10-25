"""Auth QR / OIDC mobile routes (strangler extract)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.models import AuthQrConfirmBody, OidcExchangeBody
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter()

# ── 认证 ──


@router.post("/auth/qr/confirm")
async def mobile_auth_qr_confirm(body: AuthQrConfirmBody, request: Request):
    """手机确认 PC 扫码登录。"""
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import run_market_first_login
    from app.application.session_account_meta import normalize_account_kind
    from app.fastapi_routes.domains.auth.routes import (
        _jit_create_local_user_for_enterprise,
        _market_user_email_from_raw,
    )
    from app.fastapi_routes.market_account import login_market_with_password
    from app.mod_sdk.product_skus import resolve_product_sku
    from app.security.auth_qr_login import confirm_auth_qr, get_auth_qr

    rec = get_auth_qr(body.qr_id)
    if not rec or rec.get("status") == "expired":
        return JSONResponse(
            format_mobile_response(None, "二维码已过期", success=False, code=400),
            status_code=400,
        )

    username = (body.username or "").strip()
    password = body.password or ""
    auth_app_service = get_auth_app_service()
    sku = resolve_product_sku() or "personal"
    # Do not put ``__fields_set__`` in a nested getattr default: Python eagerly
    # evaluates defaults, which touches Pydantic v2's deprecated compatibility
    # property even when ``model_fields_set`` exists.
    fields_set = getattr(body, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(body, "__dict__", {}).get("__fields_set__", set())
    qr_account_kind = str(rec.get("account_kind") or "").strip()
    body_account_kind = body.account_kind if "account_kind" in fields_set else qr_account_kind
    account_kind = normalize_account_kind(
        body_account_kind,
        default=qr_account_kind or ("enterprise" if sku == "enterprise" else "personal"),
    )

    authorization = request.headers.get("Authorization") or ""
    if authorization.startswith("Bearer ") and not username:
        from app.security.mobile_jwt import user_id_from_mobile_bearer

        uid = user_id_from_mobile_bearer(authorization)
        if uid:
            from app.db.models.user import User
            from app.db.session import get_db

            with get_db() as db:
                row = db.query(User).filter(User.id == int(uid)).first()
                if row:
                    username = str(row.username or "")

    if not username or not password:
        return JSONResponse(
            format_mobile_response(None, "请提供账号与密码确认登录", success=False, code=400),
            status_code=400,
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
    )
    if err:
        msg = "登录失败"
        if hasattr(err, "body") and err.body:
            try:
                import json as _json

                msg = _json.loads(bytes(err.body).decode("utf-8")).get("message") or msg
            except RECOVERABLE_ERRORS:
                pass
        return JSONResponse(
            format_mobile_response(None, msg, success=False, code=401),
            status_code=401,
        )
    session_id = str((result or {}).get("session_id") or "")
    if not session_id:
        return JSONResponse(
            format_mobile_response(None, "会话创建失败", success=False, code=500),
            status_code=500,
        )
    ok = confirm_auth_qr(body.qr_id.strip(), session_id=session_id, login_payload=result or {})
    if not ok:
        return JSONResponse(
            format_mobile_response(None, "二维码无效", success=False, code=400),
            status_code=400,
        )
    return format_mobile_response(data={"confirmed": True, "qr_id": body.qr_id.strip()})


@router.post("/auth/oidc/exchange")
async def mobile_auth_oidc_exchange(body: OidcExchangeBody):
    """Android Custom Tabs OIDC 回调换 mobile JWT。"""
    from app.application.auth_app_service import get_auth_app_service
    from app.application.enterprise_login_flow import finalize_auth_after_oidc
    from app.application.session_account_meta import normalize_account_kind
    from app.infrastructure.auth.oidc_provider import (
        exchange_oidc_authorization,
        verify_oidc_state,
    )
    from app.mod_sdk.product_skus import resolve_product_sku
    from app.security.mobile_jwt import issue_mobile_tokens

    ok, _rt = verify_oidc_state(body.state)
    if not ok:
        return JSONResponse(
            format_mobile_response(None, "OIDC state 无效", success=False, code=400),
            status_code=400,
        )
    try:
        oidc_session = await exchange_oidc_authorization(body.code)
        raw_profile = oidc_session.get("profile")
        profile: dict[str, Any] = dict(raw_profile) if isinstance(raw_profile, dict) else {}
    except RECOVERABLE_ERRORS:
        return JSONResponse(
            format_mobile_response(None, "OIDC 登录服务暂不可用", success=False, code=502),
            status_code=502,
        )
    auth_app_service = get_auth_app_service()
    auth_result = auth_app_service.authenticate_oidc_user(profile)
    if not auth_result.get("success"):
        return JSONResponse(
            format_mobile_response(
                None,
                str(auth_result.get("message") or "OIDC 登录失败"),
                success=False,
                code=401,
            ),
            status_code=401,
        )
    sku = resolve_product_sku() or "personal"
    account_kind = normalize_account_kind(
        None, default="enterprise" if sku == "enterprise" else "personal"
    )
    username = str((auth_result.get("user") or {}).get("username") or "")
    session_id = auth_result.get("session_id")
    payload = await finalize_auth_after_oidc(
        auth_result=auth_result,
        oidc_profile=profile,
        oidc_access_token=str(oidc_session.get("access_token") or ""),
        account_kind=account_kind,
        sku=sku,
    )
    user_raw = payload.get("user") or {}
    tokens = issue_mobile_tokens(
        user_id=int(user_raw["id"]),
        session_id=str(session_id),
        account_kind=str(payload.get("account_kind") or account_kind),
        username=username,
    )
    data: dict[str, Any] = {
        "user": user_raw,
        "session_id": session_id,
        "account_kind": payload.get("account_kind") or account_kind,
        **tokens,
    }
    for key in (
        "market_access_token",
        "market_refresh_token",
        "company_brand",
        "market_is_admin",
        "market_is_enterprise",
    ):
        if key in payload and payload[key] is not None:
            data[key] = payload[key]
    return format_mobile_response(data=data)
