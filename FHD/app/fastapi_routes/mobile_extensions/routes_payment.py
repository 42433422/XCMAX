"""PaymentRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.application.mobile_extensions.protocols import (
    AuthHeaderCall,
    LatestMarketTokenCall,
    MarketBaseUrlCall,
    MarketProxyCall,
    MobileCheckoutSignBodyCall,
    MobileMarketAuthorizationCall,
    MobilePrincipal,
    MobileUnauthorizedResponseCall,
    NormalizeMobilePaymentChannelCall,
    RequestSessionIdCall,
    ResolveMarketTokenCall,
    SessionMarketTokenCall,
    UserDependency,
    VerifyJwtCall,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaymentRoutesPorts:
    mobile_market_authorization: MobileMarketAuthorizationCall
    mobile_unauthorized_response: MobileUnauthorizedResponseCall
    market_base_url: MarketBaseUrlCall
    market_proxy: MarketProxyCall
    mobile_checkout_sign_body: MobileCheckoutSignBodyCall
    normalize_mobile_payment_channel: NormalizeMobilePaymentChannelCall
    auth_header: AuthHeaderCall
    latest_market_token: LatestMarketTokenCall
    resolve_market_token: ResolveMarketTokenCall
    session_market_token: SessionMarketTokenCall
    verify_jwt: VerifyJwtCall
    request_session_id: RequestSessionIdCall


class PaymentRoutes:
    def __init__(self, ports: PaymentRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

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

        self._normalize_mobile_payment_channel = _normalize_mobile_payment_channel

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

        self._mobile_checkout_sign_body = _mobile_checkout_sign_body

        @router.get("/payment/plans", response_model=dict[str, Any])
        async def mobile_payment_plans(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """返回移动端可购买套餐与支付渠道。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            try:
                payload = await ports.market_proxy(
                    "GET",
                    "/api/payment/plans",
                    authorization=ports.mobile_market_authorization(request, user),
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
                        "market_base_url": ports.market_base_url(),
                        "payment_channels": list(_MOBILE_PAYMENT_CHANNELS),
                    }
                return format_mobile_response(data=payload)
            except RECOVERABLE_ERRORS:
                logger.exception("mobile payment plans failed")
                return JSONResponse(
                    format_mobile_response(None, "支付服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_payment_plans = mobile_payment_plans

        @router.post("/payment/checkout", response_model=dict[str, Any])
        async def mobile_payment_checkout(
            request: Request, body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """创建移动端支付订单并返回渠道下单参数。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            authorization = ports.mobile_market_authorization(request, user)
            if not authorization:
                return JSONResponse(
                    format_mobile_response(
                        None, "尚未绑定市场账号；请重新登录", success=False, code=401
                    ),
                    status_code=401,
                )
            try:
                checkout_body = dict(body or {})
                checkout_body["channel"] = ports.normalize_mobile_payment_channel(
                    checkout_body.get("channel")
                )
                checkout_body["client"] = str(checkout_body.get("client") or "android").strip()
                checkout_body.setdefault("return_url", "xcagi://payment/complete")
                signed = await ports.market_proxy(
                    "POST",
                    "/api/payment/sign-checkout",
                    json_body=ports.mobile_checkout_sign_body(checkout_body),
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
                payload = await ports.market_proxy(
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

        self.mobile_payment_checkout = mobile_payment_checkout

        @router.get("/payment/query/{out_trade_no}", response_model=dict[str, Any])
        async def mobile_payment_query(
            request: Request, out_trade_no: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """查询移动端支付订单状态。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            try:
                payload = await ports.market_proxy(
                    "GET",
                    f"/api/payment/query/{out_trade_no}",
                    authorization=ports.mobile_market_authorization(request, user),
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

        self.mobile_payment_query = mobile_payment_query

        @router.get("/wallet/balance", response_model=None)
        async def mobile_wallet_balance(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """返回当前用户的市场钱包余额与会员信息（供移动端"我"页面展示）。

            数据来源：market ``/api/wallet/overview`` + ``/api/payment/my-plan``。
            任一上游不可用时返回降级空值，保持 200 以便客户端渲染占位 UI。
            """
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )

            # 1) 解析移动端 session_id，优先用 session 绑定的 market token
            sid = ""
            auth_hdr = request.headers.get("Authorization") or ""
            if auth_hdr.startswith("Bearer "):
                payload = ports.verify_jwt(auth_hdr[7:].strip())
                if payload:
                    sid = str(payload.get("session_id") or "")
            if not sid:
                sid = ports.request_session_id(request)
            market_token = ""
            if sid:
                market_token = ports.session_market_token(sid)
            if not market_token:
                # 多用户环境按 user_id 过滤，防止串号（fallback 仅用于单用户桌面模式）
                market_token = ports.latest_market_token(user_id=getattr(user, "id", None))
            if sid and market_token:
                # 余额属于长会话高频读路径；访问令牌过期时用持久化 refresh_token 自动续期。
                market_token = await ports.resolve_market_token(sid)
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
            authorization = ports.auth_header(market_token)

            # 2) 拉取钱包概览
            wallet_payload = await ports.market_proxy(
                "GET",
                "/api/wallet/overview",
                authorization=authorization,
                return_error_payload=True,
            )
            if isinstance(wallet_payload, dict) and wallet_payload.get("__proxy_error__"):
                # 降级：尝试 /api/wallet/balance
                wallet_payload = await ports.market_proxy(
                    "GET",
                    "/api/wallet/balance",
                    authorization=authorization,
                    return_error_payload=True,
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
            plan_payload = await ports.market_proxy(
                "GET",
                "/api/payment/my-plan",
                authorization=authorization,
                return_error_payload=True,
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
            llm_payload = await ports.market_proxy(
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
                    "market_base_url": ports.market_base_url(),
                }
            )

        self.mobile_wallet_balance = mobile_wallet_balance
