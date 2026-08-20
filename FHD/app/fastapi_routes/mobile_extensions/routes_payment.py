"""Mobile payment / wallet routes (strangler extract)."""

from __future__ import annotations

import importlib
import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter()


def _parent():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


def _mobile_market_authorization(request: Request, user) -> str:
    return cast("str", _parent()._mobile_market_authorization(request, user))


def _mobile_unauthorized_response():
    return _parent()._mobile_unauthorized_response()


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


@router.get("/payment/plans", response_model=dict[str, Any])
async def mobile_payment_plans(request: Request, user=Depends(get_mobile_user)):
    """返回移动端可购买套餐与支付渠道。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.fastapi_routes.market_account import _market_base_url, _proxy_json

        payload = await _proxy_json(
            "GET",
            "/api/payment/plans",
            authorization=_mobile_market_authorization(request, user),
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
    except RECOVERABLE_ERRORS:
        logger.exception("mobile payment plans failed")
        return JSONResponse(
            format_mobile_response(None, "支付服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/payment/checkout", response_model=dict[str, Any])
async def mobile_payment_checkout(
    request: Request,
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """创建移动端支付订单并返回渠道下单参数。"""
    if user is None:
        return _mobile_unauthorized_response()
    authorization = _mobile_market_authorization(request, user)
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
    except RECOVERABLE_ERRORS:
        logger.exception("mobile payment checkout failed")
        return JSONResponse(
            format_mobile_response(None, "支付服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/payment/query/{out_trade_no}", response_model=dict[str, Any])
async def mobile_payment_query(
    request: Request,
    out_trade_no: str,
    user=Depends(get_mobile_user),
):
    """查询移动端支付订单状态。"""
    if user is None:
        return _mobile_unauthorized_response()
    try:
        from app.fastapi_routes.market_account import _proxy_json

        payload = await _proxy_json(
            "GET",
            f"/api/payment/query/{out_trade_no}",
            authorization=_mobile_market_authorization(request, user),
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
    except RECOVERABLE_ERRORS:
        logger.exception("mobile payment query failed")
        return JSONResponse(
            format_mobile_response(None, "支付服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/wallet/balance")
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
        resolve_valid_market_access_token,
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
    if sid and market_token:
        # 余额属于长会话高频读路径；访问令牌过期时用持久化 refresh_token 自动续期。
        market_token = await resolve_valid_market_access_token(sid)
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
        raw_wallet = wallet_payload.get("wallet")
        wallet_obj = raw_wallet if isinstance(raw_wallet, dict) else wallet_payload
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
