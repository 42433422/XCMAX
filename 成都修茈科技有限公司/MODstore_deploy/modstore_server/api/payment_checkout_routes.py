"""Checkout and Java-forwarding routes for the payment fallback API."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from modstore_server import alipay_service, payment_orders
from modstore_server.api.deps import _get_current_user
from modstore_server.api.payment_router import router
from modstore_server.application.payment_gateway import (
    PaymentGatewayService,
    java_payment_unreachable_message,
)
from modstore_server.models import User, get_session_factory
from modstore_server.payment_common import (
    CheckoutDTO,
    SignCheckoutBody,
    _checkout_return_url,
    _resolve_checkout_fields,
    canonical_checkout_sign_data,
    check_replay_attack,
    generate_signature,
    verify_signature,
)

logger = logging.getLogger(__name__)


@router.post("/sign-checkout")
def api_sign_checkout(body: SignCheckoutBody, user: User = Depends(_get_current_user)):
    """
    服务端生成支付下单签名（``PAYMENT_SECRET_KEY`` 仅在后端使用）。
    前端应使用返回的 ``request_id`` / ``timestamp`` / ``signature`` 及解析后的金额字段调用 ``POST /checkout``。
    """
    sf = get_session_factory()
    with sf() as session:
        subject, total_amount, item_id, plan_id, _order_kind, wallet_recharge = (
            _resolve_checkout_fields(session, body, user_id=user.id)
        )
    request_id = str(uuid.uuid4())
    timestamp = int(time.time())
    dto = CheckoutDTO(
        plan_id=plan_id,
        item_id=item_id,
        total_amount=total_amount,
        subject=subject,
        wallet_recharge=wallet_recharge,
        request_id=request_id,
        timestamp=timestamp,
        signature="-",
    )
    secret_key = os.environ.get("PAYMENT_SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError(
            "PAYMENT_SECRET_KEY 环境变量未设置。"
            '请设置一个强随机密钥用于支付签名，例如：python -c "import secrets; print(secrets.token_hex(32))"'
        )
    data_to_sign = canonical_checkout_sign_data(dto)
    sig = generate_signature(data_to_sign, secret_key)
    return {
        "request_id": request_id,
        "timestamp": timestamp,
        "signature": sig,
        "subject": subject,
        "total_amount": total_amount,
        "item_id": item_id,
        "plan_id": plan_id,
        "wallet_recharge": wallet_recharge,
    }


async def _forward_checkout_to_java(request: Request, body: CheckoutDTO) -> Response | None:
    """PAYMENT_BACKEND=java 时由中间件转发；若请求仍落到本路由，则直连 Java，避免误用 Python 侧支付宝配置。"""
    gw = PaymentGatewayService()
    if gw.backend != "java":
        return None
    url = f"{gw.java_url.rstrip('/')}/api/payment/checkout"
    payload = body.model_dump(exclude_none=True)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth
    ua = request.headers.get("user-agent")
    if ua:
        headers["User-Agent"] = ua
    from modstore_server.infrastructure.http_clients import get_java_client

    r: httpx.Response | None = None
    try:
        client = get_java_client()
        r = await client.post(
            url, json=payload, headers=headers, timeout=30.0, follow_redirects=False
        )
    except httpx.HTTPError as e:
        raise HTTPException(502, java_payment_unreachable_message(e)) from e
    except Exception as e:
        raise HTTPException(502, java_payment_unreachable_message(e)) from e
    if r is None:
        raise HTTPException(502, "Java 支付服务请求未完成")
    hop = {
        k: v
        for k, v in r.headers.items()
        if k.lower()
        not in {"content-length", "transfer-encoding", "connection", "content-encoding"}
    }
    return Response(content=r.content, status_code=r.status_code, headers=dict(hop))


@router.post("/checkout")
async def api_payment_checkout(
    body: CheckoutDTO,
    request: Request,
    user: User = Depends(_get_current_user),
):
    """
    创建支付宝订单（需登录）。
    模式：
      - ``wallet_recharge=true`` + ``total_amount``：钱包充值
      - ``plan_id``：购买预设套餐
      - ``item_id``：购买市场中的 MOD
    返回: ``type`` 为 ``page`` / ``wap`` / ``precreate``，对应跳转 URL 或扫码内容。
    """
    try:
        # 防重放攻击检查
        if check_replay_attack(body.request_id, body.timestamp):
            raise HTTPException(400, "请求已过期或重复")

        secret_key = os.environ.get("PAYMENT_SECRET_KEY", "")
        if not secret_key:
            raise RuntimeError(
                "PAYMENT_SECRET_KEY 环境变量未设置。"
                '请设置一个强随机密钥用于支付签名，例如：python -c "import secrets; print(secrets.token_hex(32))"'
            )

        sf = get_session_factory()
        with sf() as session:
            subject, total_amount, item_id, plan_id, order_kind, wallet_recharge = (
                _resolve_checkout_fields(
                    session,
                    SignCheckoutBody(
                        plan_id=body.plan_id,
                        item_id=body.item_id,
                        total_amount=body.total_amount,
                        subject=body.subject,
                        wallet_recharge=body.wallet_recharge,
                    ),
                    user_id=user.id,
                )
            )

        dto_verify = CheckoutDTO(
            plan_id=plan_id,
            item_id=item_id,
            total_amount=total_amount,
            subject=subject,
            wallet_recharge=wallet_recharge,
            pay_channel=(body.pay_channel or "alipay").strip() or "alipay",
            request_id=body.request_id,
            timestamp=body.timestamp,
            signature=body.signature,
        )
        data_to_sign = canonical_checkout_sign_data(dto_verify)
        if not verify_signature(data_to_sign, secret_key, body.signature):
            raise HTTPException(400, "签名验证失败")

        java_response = await _forward_checkout_to_java(request, dto_verify)
        if java_response is not None:
            return java_response

        # Phase A: Python Alipay 下单路径已进入弃用状态。
        # 生产环境应设置 PAYMENT_BACKEND=java；中间件会在到达此处前完成代理。
        # 若到达此处说明 PAYMENT_BACKEND != java，仅允许本地开发。
        if not payment_orders.is_local_source_of_truth():
            raise HTTPException(
                503,
                "支付路由配置错误：PAYMENT_BACKEND=java 时请求应由中间件代理到 Java，"
                "未预期到达 Python checkout 路径。请检查中间件配置。",
            )

        user_id = user.id

        if not alipay_service.alipay_ui_ready():
            detail = alipay_service.alipay_not_ready_reason()
            raise HTTPException(
                503,
                (
                    "支付宝支付未配置，请联系管理员。"
                    f" 缺失项：{detail}"
                    "（管理员登录后可请求 GET /api/payment/diagnostics 查看明细）"
                ),
            )

        out_trade_no = f"MOD{int(time.time())}{user_id:06d}"
        order_result = payment_orders.create(
            out_trade_no=out_trade_no,
            subject=subject,
            total_amount=f"{total_amount:.2f}",
            user_id=user_id,
            item_id=item_id,
            plan_id=plan_id,
            order_kind=order_kind,
        )
        if not order_result["ok"]:
            raise HTTPException(500, f"创建订单失败: {order_result.get('message')}")

        from modstore_server.account_lifecycle import mark_pending_payment

        mark_pending_payment(int(user_id), plan_id=plan_id)

        ua = request.headers.get("user-agent", "")
        return_url = _checkout_return_url(request, out_trade_no)
        notify_url = (
            os.environ.get("ALIPAY_NOTIFY_URL") or ""
        ).strip() or alipay_service.notify_url_default()
        pay_result = alipay_service.create_pay_order(
            out_trade_no=out_trade_no,
            subject=subject,
            total_amount=f"{total_amount:.2f}",
            user_agent=ua,
            return_url=return_url,
            quit_url=return_url,
            notify_url=notify_url,
        )

        if not pay_result["ok"]:
            payment_orders.update_status(out_trade_no=out_trade_no, status="failed")
            raise HTTPException(502, f"支付下单失败: {pay_result.get('message')}")

        extras: dict[str, Any] = {"pay_type": pay_result.get("type")}
        if pay_result.get("qr_code"):
            extras["qr_code"] = pay_result["qr_code"]
        payment_orders.merge_fields(out_trade_no, **extras)

        return {
            "ok": True,
            "order_id": out_trade_no,
            "type": pay_result["type"],
            "redirect_url": pay_result.get("redirect_url"),
            "qr_code": pay_result.get("qr_code"),
            "subject": subject,
            "total_amount": total_amount,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("支付下单异常: %s", e)
        raise HTTPException(500, "系统内部错误，请稍后重试")
