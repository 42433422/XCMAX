"""Mobile 认证 / 联系人 / 客服 / 支付 / 钱包 routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

auth_payment_router = APIRouter()

from app.fastapi_routes.mobile_extensions.models import AuthQrConfirmBody, OidcExchangeBody
from app.utils.operational_errors import RECOVERABLE_ERRORS

RECOVERABLE_ERRORS = RECOVERABLE_ERRORS

# ── 认证 ──


@auth_payment_router.post("/auth/qr/confirm")
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
    sku = resolve_product_sku()
    fields_set = getattr(body, "model_fields_set", getattr(body, "__fields_set__", set()))
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

                msg = _json.loads(err.body.decode("utf-8")).get("message") or msg
            except mext.OPERATIONAL_ERRORS:
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


@auth_payment_router.post("/auth/oidc/exchange")
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
        profile = (
            oidc_session.get("profile") if isinstance(oidc_session.get("profile"), dict) else {}
        )
    except mext.OPERATIONAL_ERRORS as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=502),
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
    sku = resolve_product_sku()
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


# ── 联系人固定区组成（surface SSOT 派生） ──


@auth_payment_router.get("/contacts/fixed")
async def get_mobile_fixed_contacts(request: Request, user=Depends(get_mobile_user)):
    """返回手机端联系人固定区(按端 SSOT 派生)。

    top/bottom 以平台员工为界:渲染顺序 = top + 平台员工(动态) + bottom。
    管理端不含专属客服(由 surface SSOT 自动 gating);两端均含小C与超级员工。
    """
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.surface_contacts import mobile_fixed_contacts

    return format_mobile_response(data=mobile_fixed_contacts(mext._mobile_group_mode(request)))


# ── 专属客服接口（企业版手机端） ──


@auth_payment_router.get("/cs/info")
async def get_cs_info(request: Request, user=Depends(get_mobile_user)):
    """返回当前用户的小C/智能客服信息。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    return format_mobile_response(
        data={
            "cs_available": True,
            "cs_name": "企业专属客服",
            "cs_avatar": None,
            "cs_online": True,
            "backend": "enterprise-cs",
        }
    )


@auth_payment_router.post("/cs/messages")
async def post_cs_message(request: Request, body: dict, user=Depends(get_mobile_user)):
    """发送消息到企业桌面端同源智能客服通道。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    msg_body = str(body.get("body", "") or "").strip()
    if not msg_body:
        return JSONResponse(
            format_mobile_response(None, "消息不能为空", success=False, code=400),
            status_code=400,
        )
    # 专属客服 = 企业客户↔运营者管理端的真实 IM 通道(与桌面端同源 enterprise-cs),不再复用小C LLM。
    # 客户消息写入 IM,运营者在管理端「客服收件箱」收到并以「企业专属客服」身份回复。
    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs = svc._ensure_enterprise_dedicated_cs_user()
            if cs is None or int(cs.id) == uid:
                return JSONResponse(
                    format_mobile_response(None, "客服通道不可用", success=False, code=500),
                    status_code=500,
                )
            conv = svc.get_or_create_direct(uid, int(cs.id))
            result = svc.send_message(int(conv["id"]), uid, msg_body)
        sent = result.get("message") or {}
        return format_mobile_response(
            data={
                "message_id": str(sent.get("id") or ""),
                # 真实客服:无 LLM 自动回复;客户端见空 reply 即 loadMessages 刷新等运营者回复。
                "reply": "",
                "backend": "enterprise-cs",
                "timestamp": str(sent.get("created_at") or ""),
            }
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile cs send via IM failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@auth_payment_router.get("/cs/messages")
async def get_cs_messages(
    request: Request, since: str | None = None, user=Depends(get_mobile_user)
):
    """拉取小C/智能客服消息。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    # 从 enterprise-cs 真实 IM 会话拉取消息(客户发的 + 运营者以「企业专属客服」回复的)。
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    uid = mext._mobile_request_user_id(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    error = ""
    messages: list[dict[str, Any]] = []
    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs = svc._ensure_enterprise_dedicated_cs_user()
            if cs is not None and int(cs.id) != uid:
                conv = svc.get_or_create_direct(uid, int(cs.id))
                raw = svc.list_messages(int(conv["id"]), uid, limit=100)
                messages = [
                    {
                        "messageId": str(m.get("id") or ""),
                        # 发送者是自己=user,否则=客服(运营者以 enterprise-cs 身份回复)。
                        "sender": "user" if int(m.get("sender_user_id") or 0) == uid else "cs",
                        "body": str(m.get("body") or ""),
                        "timestamp": str(m.get("created_at") or ""),
                    }
                    for m in raw
                ]
    except mext.OPERATIONAL_ERRORS as exc:
        logger.warning("mobile cs message history (IM) unavailable: %s", exc)
        error = str(exc)[:300]
    if since:
        messages = [m for m in messages if str(m.get("timestamp") or "") > since]
    return format_mobile_response(data={"messages": messages, "persist_error": error})


# ── 钱包 / 余额 ──

_MOBILE_PAYMENT_CHANNELS: tuple[dict[str, str], ...] = (
    {
        "id": "mobile_h5",
        "title": "手机网页",
        "description": "统一收银台，适合 App 内或手机浏览器打开",
    },
    {
        "id": "alipay",
        "title": "支付宝",
        "description": "支付宝 H5 / 跳转支付，取决于市场侧配置",
    },
    {
        "id": "wechat_h5",
        "title": "微信支付",
        "description": "微信 H5 支付，取决于市场侧配置",
    },
)


def _normalize_mobile_payment_channel(raw: Any) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    aliases = {
        "": "mobile_h5",
        "mobile": "mobile_h5",
        "h5": "mobile_h5",
        "wap": "mobile_h5",
        "alipay_h5": "alipay",
        "zhifubao": "alipay",
        "wechat": "wechat_h5",
        "weixin": "wechat_h5",
        "weixin_h5": "wechat_h5",
    }
    value = aliases.get(value, value)
    allowed = {item["id"] for item in _MOBILE_PAYMENT_CHANNELS}
    return value if value in allowed else "mobile_h5"


def _mobile_checkout_sign_body(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if body.get("plan_id"):
        out["plan_id"] = str(body.get("plan_id"))
    wallet_recharge = body.get("wallet_recharge")
    if wallet_recharge is True or str(wallet_recharge).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        out["wallet_recharge"] = True
        try:
            out["total_amount"] = float(body.get("total_amount") or 0)
        except (TypeError, ValueError):
            out["total_amount"] = 0.0
        out["subject"] = str(body.get("subject") or "钱包充值")
    for key in ("out_trade_no", "metadata"):
        if key in body:
            out[key] = body[key]
    return out


@auth_payment_router.get("/payment/plans", response_model=dict[str, Any])
async def mobile_payment_plans(request: Request, user=Depends(get_mobile_user)):
    """返回移动端可购买套餐与支付渠道。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    try:
        from app.fastapi_routes.market_account import _market_base_url, _proxy_json

        payload = await _proxy_json(
            "GET",
            "/api/payment/plans",
            authorization=mext._mobile_market_authorization(request, user),
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status = int(payload.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    payload.get("payload"), "套餐加载失败", success=False, code=status
                ),
                status_code=status,
            )
        if isinstance(payload, dict):
            payload = {
                **payload,
                "market_base_url": _market_base_url(),
                "payment_channels": list(_MOBILE_PAYMENT_CHANNELS),
            }
        return format_mobile_response(data=payload)
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile payment plans failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@auth_payment_router.post("/payment/checkout", response_model=dict[str, Any])
async def mobile_payment_checkout(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """创建移动端支付订单并返回渠道下单参数。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    authorization = mext._mobile_market_authorization(request, user)
    if not authorization:
        return JSONResponse(
            format_mobile_response(None, "尚未绑定市场账号；请重新登录", success=False, code=401),
            status_code=401,
        )
    try:
        from app.fastapi_routes.market_account import _proxy_json

        checkout_body = dict(body or {})
        checkout_body["channel"] = _normalize_mobile_payment_channel(checkout_body.get("channel"))
        checkout_body["client"] = str(checkout_body.get("client") or "android").strip()
        checkout_body.setdefault("return_url", "xcagi://payment/complete")
        signed = await _proxy_json(
            "POST",
            "/api/payment/sign-checkout",
            json_body=_mobile_checkout_sign_body(checkout_body),
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(signed, dict) and signed.get("__proxy_error__"):
            status = int(signed.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    signed.get("payload"), "支付签名失败", success=False, code=status
                ),
                status_code=status,
            )
        if isinstance(signed, dict):
            checkout_body.update(signed)
        payload = await _proxy_json(
            "POST",
            "/api/payment/checkout",
            json_body=checkout_body,
            authorization=authorization,
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status = int(payload.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    payload.get("payload"), "支付下单失败", success=False, code=status
                ),
                status_code=status,
            )
        return format_mobile_response(data=payload, message="下单成功")
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile payment checkout failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@auth_payment_router.get("/payment/query/{out_trade_no}", response_model=dict[str, Any])
async def mobile_payment_query(
    request: Request,
    out_trade_no: str,
    user=Depends(get_mobile_user),
):
    """查询移动端支付订单状态。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    try:
        from app.fastapi_routes.market_account import _proxy_json

        payload = await _proxy_json(
            "GET",
            f"/api/payment/query/{out_trade_no}",
            authorization=mext._mobile_market_authorization(request, user),
            return_error_payload=True,
        )
        if isinstance(payload, dict) and payload.get("__proxy_error__"):
            status = int(payload.get("status_code") or 502)
            return JSONResponse(
                format_mobile_response(
                    payload.get("payload"), "订单查询失败", success=False, code=status
                ),
                status_code=status,
            )
        return format_mobile_response(data=payload)
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile payment query failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@auth_payment_router.get("/wallet/balance")
async def mobile_wallet_balance(request: Request, user=Depends(get_mobile_user)):
    """返回当前用户的市场钱包余额与会员信息（供移动端"我"页面展示）。

    数据来源：market ``/api/wallet/overview`` + ``/api/payment/my-plan``。
    任一上游不可用时返回降级空值，保持 200 以便客户端渲染占位 UI。
    """
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.fastapi_routes.market_account import (
        _auth_header,
        _market_base_url,
        _proxy_json,
        latest_session_market_token,
        session_market_token,
    )
    from app.security.mobile_jwt import verify_mobile_jwt

    # 1) 解析移动端 session_id，优先用 session 绑定的 market token
    sid = ""
    auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.startswith("Bearer "):
        payload = verify_mobile_jwt(auth_hdr[7:].strip())
        if payload:
            sid = str(payload.get("session_id") or "")
    if not sid:
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
    market_token = ""
    if sid:
        market_token = session_market_token(sid)
    if not market_token:
        # 多用户环境按 user_id 过滤，防止串号（fallback 仅用于单用户桌面模式）
        market_token = latest_session_market_token(user_id=getattr(user, "id", None))
    if not market_token:
        return format_mobile_response(
            data={
                "balance": None,
                "currency": "CNY",
                "membership_level": None,
                "experience": None,
                "byok_configured": False,
                "synced": False,
                "message": "尚未绑定市场账号",
            }
        )
    authorization = _auth_header(market_token)

    # 2) 拉取钱包概览
    wallet_payload = await _proxy_json(
        "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
    )
    if isinstance(wallet_payload, dict) and wallet_payload.get("__proxy_error__"):
        # 降级：尝试 /api/wallet/balance
        wallet_payload = await _proxy_json(
            "GET", "/api/wallet/balance", authorization=authorization, return_error_payload=True
        )
    wallet_obj: dict[str, Any] = {}
    if isinstance(wallet_payload, dict) and not wallet_payload.get("__proxy_error__"):
        wallet_obj = (
            wallet_payload.get("wallet")
            if isinstance(wallet_payload.get("wallet"), dict)
            else wallet_payload
        )
    elif isinstance(wallet_payload, dict) and wallet_payload.get("__proxy_error__"):
        logger.warning(
            "mobile_wallet_balance: wallet overview unavailable: %s",
            wallet_payload.get("payload"),
        )

    # 3) 拉取套餐/会员信息
    plan_payload = await _proxy_json(
        "GET", "/api/payment/my-plan", authorization=authorization, return_error_payload=True
    )
    plan_obj: dict[str, Any] = {}
    if isinstance(plan_payload, dict) and not plan_payload.get("__proxy_error__"):
        plan_obj = plan_payload if isinstance(plan_payload, dict) else {}
    elif isinstance(plan_payload, dict) and plan_payload.get("__proxy_error__"):
        logger.warning(
            "mobile_wallet_balance: my-plan unavailable: %s",
            plan_payload.get("payload"),
        )

    # 4) 拉取 BYOK 状态
    llm_payload = await _proxy_json(
        "GET", "/api/llm/status", authorization=authorization, return_error_payload=True
    )
    byok_count = 0
    if isinstance(llm_payload, dict) and not llm_payload.get("__proxy_error__"):
        providers = llm_payload.get("providers") or []
        byok_count = len(
            [p for p in providers if isinstance(p, dict) and p.get("has_user_override")]
        )

    # 5) 组装简化余额信息
    balance_raw = wallet_obj.get("balance")
    try:
        balance_val = float(balance_raw) if balance_raw is not None else None
    except (TypeError, ValueError):
        balance_val = None
    membership = plan_obj.get("membership") if isinstance(plan_obj, dict) else None
    membership_level = None
    if isinstance(membership, dict):
        membership_level = (
            membership.get("level") or membership.get("name") or membership.get("tier")
        )
    elif isinstance(membership, str):
        membership_level = membership
    experience = None
    if isinstance(membership, dict):
        experience = membership.get("experience") or membership.get("exp")

    return format_mobile_response(
        data={
            "balance": balance_val,
            "currency": str(wallet_obj.get("currency") or "CNY"),
            "membership_level": membership_level,
            "experience": experience,
            "byok_configured": byok_count > 0,
            "byok_count": byok_count,
            "synced": balance_val is not None,
            "market_base_url": _market_base_url(),
        }
    )
