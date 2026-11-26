"""模型支付页（Vue ModelPaymentView）兼容 API：演示套餐与支付宝预下单。"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.errors import ErrorCode, PaymentError
from app.fastapi_routes.model_payment_authorization import (
    owned_payment_order,
    require_local_payment_backend,
)
from app.fastapi_routes.model_payment_plans import DEMO_PLANS as _DEMO_PLANS
from app.infrastructure.billing.saas_plans import (
    _demo_payment_enabled,
    list_saas_plans,
    load_saas_plans_config,
    plan_by_id,
    pricing_plans_for_budget,
)
from app.infrastructure.payment import alipay as mp_ali
from app.infrastructure.payment import order_store as mp_orders
from app.infrastructure.payment.payment_sot import (
    MODEL_PAYMENT_JSON_DEPRECATED_AFTER,
    is_fhd_postgres_payment_sot,
    is_json_legacy_payment_sot,
    is_local_model_payment_sot,
    is_modstore_payment_sot,
    model_payment_backend,
    modstore_payment_hint,
)
from app.utils.operational_errors import INFRA_TRANSIENT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/model-payment", tags=["model-payment"])


def _integration_flags() -> dict[str, Any]:
    """支付宝：APPID + 应用私钥 + 支付宝公钥 + 已安装 SDK 时为已开通。"""
    return {
        "alipay_configured": mp_ali.alipay_ui_ready(),
        "market_sot": is_modstore_payment_sot(),
        "postgres_sot": is_fhd_postgres_payment_sot(),
        "backend": model_payment_backend(),
    }


def _all_plans() -> list[dict[str, Any]]:
    return (list(_DEMO_PLANS) if _demo_payment_enabled() else []) + list_saas_plans()


def _plan_by_id(plan_id: str) -> dict[str, Any] | None:
    return plan_by_id(plan_id, extra_plans=_DEMO_PLANS)


@router.get("/plans")
def get_plans(budget_range: str = ""):
    budget = (budget_range or "").strip()
    saas_plans = pricing_plans_for_budget(budget if budget else None)
    return JSONResponse(
        {
            "success": True,
            "data": {
                "plans": (list(_DEMO_PLANS) if _demo_payment_enabled() else []) + saas_plans,
                "integration": _integration_flags(),
                "budget_range": budget or None,
                "commercial_terms": load_saas_plans_config().get("commercial_terms", {}),
            },
        }
    )


@router.get("/wechat-redirect")
def wechat_redirect(plan_id: str, market_user_id: int = 0):
    """FHD 宿主微信支付：重定向至修茈市场统一收银台。"""
    from app.infrastructure.payment.modstore_payment_proxy import wechat_checkout_redirect_url

    url = wechat_checkout_redirect_url(plan_id, market_user_id=market_user_id)
    if not url:
        return JSONResponse(
            {"success": False, "message": "请配置 XCAGI_MARKET_BASE_URL"},
            status_code=503,
        )
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=url, status_code=302)


@router.post("/checkout")
def checkout(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    user_agent: str | None = Header(default=None),
):
    from app.infrastructure.auth.dependencies import get_logged_in_user, session_id_from_request

    checkout_user = get_logged_in_user(request)
    local_user_id = int(checkout_user.id)
    plan_id = str(body.get("plan_id") or "").strip()
    known_plan = _plan_by_id(plan_id)
    if known_plan and plan_id not in {p["id"] for p in _all_plans()}:
        raise PaymentError(
            ErrorCode.PAYMENT_ORDER_NOT_FOUND,
            message="该套餐已停止新购，历史订单和已购权益继续有效",
            status_code=400,
        )
    if is_modstore_payment_sot():
        from app.infrastructure.payment.modstore_payment_proxy import checkout_session_token

        market_token = checkout_session_token(session_id_from_request(request), local_user_id)
        if not market_token:
            raise HTTPException(status_code=401, detail="请先绑定当前会话的市场账号")
        channel = str(body.get("channel") or "alipay").strip().lower()
        proxy_failed = False
        if plan_id:
            from app.infrastructure.payment.modstore_payment_proxy import proxy_checkout

            proxied = proxy_checkout(plan_id=plan_id, channel=channel, auth_token=market_token)
            if proxied.get("success"):
                return JSONResponse({"success": True, "data": proxied.get("data")})
            proxy_failed = True
        return JSONResponse(
            {
                "success": False,
                "message": modstore_payment_hint(),
                "data": {
                    "use_checkout": "/api/market/payment/checkout",
                    "use_plans": "/api/market/payment/plans",
                    "proxy_error": "market_checkout_unavailable" if proxy_failed else None,
                },
            },
            status_code=409,
        )
    require_local_payment_backend()
    if is_json_legacy_payment_sot():
        import os

        dbu = (os.environ.get("DATABASE_URL") or "").strip().lower()
        if "postgresql" in dbu or "postgres://" in dbu:
            return JSONResponse(
                {
                    "success": False,
                    "message": (
                        "检测到 PostgreSQL DATABASE_URL；本地 PostgreSQL 订单后端尚未实现，"
                        "请使用已绑定账号的市场支付（MODEL_PAYMENT_BACKEND=modstore）。"
                        f"JSON 订单存储将于 {MODEL_PAYMENT_JSON_DEPRECATED_AFTER} 后废弃。"
                    ),
                    "data": {
                        "supported_backend": "modstore",
                        "postgres_order_store_available": False,
                    },
                },
                status_code=409,
            )
    legacy_channel = str(body.get("channel") or "").strip().lower()
    if legacy_channel and legacy_channel != "alipay":
        return JSONResponse(
            {"success": False, "message": "仅支持支付宝；请移除 channel 或传 channel=alipay"},
            status_code=400,
        )
    plan = _plan_by_id(plan_id)
    if not plan:
        raise PaymentError(
            ErrorCode.PAYMENT_ORDER_NOT_FOUND,
            message=f"未知套餐: {plan_id}",
            status_code=400,
        )
    if plan.get("license_type") in {"trial", "permanent"}:
        from app.application.tenant_subscription_app_service import subscription_status_for_user

        current = subscription_status_for_user(local_user_id)
        existing = plan_by_id(str(current.get("plan_id") or "")) or {}
        if existing.get("license_type") == "permanent":
            return JSONResponse(
                {"success": False, "message": "已拥有软件永久授权，无需重复购买"},
                status_code=409,
            )

    order_id = f"mp-{uuid.uuid4().hex[:18]}"
    channel = "alipay"
    amount_yuan = f"{int(plan['amount_cents']) / 100:.2f}"
    subject = str(plan["title"])

    mp_ali.warn_notify_url_path_once()

    if not mp_ali.alipay_ui_ready():
        hint = (
            "当前为演示模式：未满足支付宝真实下单条件（需 ALIPAY_APP_ID、ALIPAY_APP_PRIVATE_KEY 或 "
            "ALIPAY_APP_PRIVATE_KEY_PATH、支付宝公钥（环境变量或默认 424/alipayPublicKey_RSA2.txt），"
            "并安装 python-alipay-sdk；沙箱请加 ALIPAY_DEBUG=1）。"
        )
        if mp_ali.credentials_ready() and mp_ali.sdk_import_error():
            hint = mp_ali.sdk_import_error() or hint
        logger.info(
            "[model-payment] demo checkout order_id=%s plan=%s (alipay not ready)",
            order_id,
            plan_id,
        )
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "order_id": order_id,
                    "channel": channel,
                    "status": "demo_pending",
                    "amount_cents": plan["amount_cents"],
                    "plan_id": plan_id,
                    "client_payload": {"demo": True},
                    "redirect_url": None,
                    "qr_code": None,
                    "setup_hint": hint,
                },
            }
        )

    # 自动根据 User-Agent 选择 page.pay / wap.pay / 回退 precreate
    pay_res = mp_ali.create_pay_order(
        out_trade_no=order_id,
        subject=subject,
        total_amount=amount_yuan,
        user_agent=user_agent or "",
    )

    if not pay_res["success"]:
        logger.warning(
            "[model-payment] pay_order failed order_id=%s message=%s raw=%s",
            order_id,
            pay_res.get("message"),
            pay_res.get("raw"),
        )
        return JSONResponse(
            {
                "success": False,
                "message": pay_res.get("message") or "支付宝下单失败",
            }
        )

    logger.info(
        "[model-payment] pay_order ok order_id=%s type=%s",
        order_id,
        pay_res.get("type"),
    )
    try:
        mp_orders.record_checkout_pending(
            out_trade_no=order_id,
            plan_id=plan_id,
            amount_cents=int(plan["amount_cents"]),
            amount_yuan=amount_yuan,
            local_user_id=local_user_id,
            tenant_id=checkout_user.tenant_id,
        )
    except (OSError, ValueError) as e:
        logger.exception("[model-payment] 写入本地订单失败（notify 将无法幂等关联）: %s", e)
        return JSONResponse(
            {"success": False, "message": "订单记录失败，尚未提供付款入口，请稍后重试"},
            status_code=503,
        )

    return JSONResponse(
        {
            "success": True,
            "data": {
                "order_id": order_id,
                "channel": channel,
                "status": "pending_payment",
                "amount_cents": plan["amount_cents"],
                "plan_id": plan_id,
                "client_payload": pay_res.get("raw"),
                "redirect_url": pay_res.get("redirect_url"),
                "qr_code": pay_res.get("qr_code"),
            },
        }
    )


@router.post("/notify/alipay")
async def alipay_trade_notify(request: Request):
    """
    支付宝异步通知（需在开放平台配置 notify_url 指向本地址的公网 URL）。
    验签通过后返回纯文本 success；请勿在本接口中信任未验签参数做发货。
    """
    if is_fhd_postgres_payment_sot():
        return PlainTextResponse("fail", status_code=503)
    if not is_local_model_payment_sot():
        return PlainTextResponse("fail", status_code=410)
    try:
        form = await request.form()
    except INFRA_TRANSIENT as e:
        logger.warning("alipay notify: bad form: %s", e)
        return PlainTextResponse("fail", status_code=400)

    data: dict[str, str] = {str(k): str(v) for k, v in form.items()}
    signature = data.pop("sign", None)
    if not signature:
        return PlainTextResponse("fail", status_code=400)

    if not mp_ali.credentials_ready():
        logger.error("alipay notify: credentials not configured")
        return PlainTextResponse("fail", status_code=503)

    try:
        ok = mp_ali.verify_notify(data, signature)
    except INFRA_TRANSIENT as e:
        logger.exception("alipay notify verify error: %s", e)
        return PlainTextResponse("fail", status_code=500)

    if not ok:
        logger.warning("alipay notify: signature verification failed")
        return PlainTextResponse("fail", status_code=400)

    trade_status = data.get("trade_status", "")
    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        out_trade_no = str(data.get("out_trade_no") or "")
        trade_no = str(data.get("trade_no") or "")
        total_amount = str(data.get("total_amount") or "")
        try:
            reason, snap = mp_orders.apply_notify_paid(
                out_trade_no=out_trade_no,
                trade_no=trade_no,
                total_amount=total_amount,
            )
        except (OSError, ValueError):
            # Do not acknowledge a verified payment if the quarantine or
            # authoritative local order cannot be read/written durably.
            logger.exception("[model-payment] verified notification persistence failed")
            return PlainTextResponse("fail", status_code=503)
        if reason in {"amount_mismatch", "trade_mismatch", "invalid_notify"}:
            return PlainTextResponse("fail", status_code=400)
        if reason in {"fulfillment_pending", "unknown_order", "reconciliation_required", "order_record_corrupt", "terminal_order_conflict"}:
            # Unknown orders are unsettled money, not a successful delivery.
            # Never stop provider retries before an operator can reconcile
            # the merchant order ID against the authoritative payment record.
            if reason == "unknown_order":
                logger.error(
                    "[model-payment] unmatched verified payment notification requires reconciliation: out_trade_no=%s",
                    out_trade_no,
                )
            return PlainTextResponse("fail", status_code=503)
        if reason == "marked_paid" and snap:
            ent = snap.get("entitlement") if isinstance(snap, dict) else None
            logger.info(
                "[model-payment] 权益已发放 plan_id=%s amount_cents=%s purchase_count=%s",
                snap.get("plan_id"),
                snap.get("amount_cents"),
                (ent or {}).get("purchase_count") if isinstance(ent, dict) else None,
            )
    return PlainTextResponse("success")


@router.get("/diagnostics")
def diagnostics():
    """只读诊断：返回支付宝配置是否就绪、各字段来源、notify URL 是否对齐等，不含密钥内容。"""
    data = mp_ali.diagnostics_snapshot()
    backend = model_payment_backend()
    data["sot_backend"] = backend
    data["store_path"] = str(mp_orders.order_store_path())
    if is_fhd_postgres_payment_sot():
        data["db_table"] = None
        data["backend_available"] = False
        data["backend_error"] = "postgres_order_store_not_implemented"
    return JSONResponse({"success": True, "data": data})


@router.get("/entitlements")
def entitlements():
    """已购权益列表（按 last_paid_at 倒序）。"""
    if is_modstore_payment_sot():
        return JSONResponse(
            {
                "success": False,
                "message": modstore_payment_hint(),
                "data": {"entitlements": []},
            },
            status_code=409,
        )
    require_local_payment_backend()
    items = mp_orders.list_entitlements()
    return JSONResponse(
        {"success": True, "data": {"entitlements": items, "backend": model_payment_backend()}}
    )


@router.get("/usage")
def usage(limit: int = 50, run_id: str = "", user_id: str = ""):
    """AI 用量账本：AgentRun/XCauto/工具/员工成本审计与钱包扣费对账入口。"""
    from app.infrastructure.billing.model_usage import (
        get_model_wallet,
        list_model_usage_entries,
        model_usage_database_path,
        model_usage_wallet_backend,
    )

    items = list_model_usage_entries(limit=limit, run_id=run_id, user_id=user_id)
    wallet = get_model_wallet(user_id) if user_id else None
    return JSONResponse(
        {
            "success": True,
            "data": {
                "entries": items,
                "count": len(items),
                "wallet": wallet,
                "wallet_backend": model_usage_wallet_backend(),
                "ledger_path": str(model_usage_database_path()),
                "backend": model_payment_backend(),
            },
        }
    )


def _same_amount_in_cents(amount: Any, expected_cents: int) -> bool:
    try:
        candidate = Decimal(str(amount)) * 100
        return (
            candidate.is_finite()
            and candidate == candidate.to_integral_value()
            and int(candidate) == expected_cents
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


@router.get("/query/{out_trade_no}")
def query_trade(request: Request, out_trade_no: str):
    """alipay.trade.query：查询交易状态。同时返回本地订单快照。"""
    local = owned_payment_order(request, out_trade_no)
    res = mp_ali.query_order(out_trade_no=out_trade_no)
    if not res["success"]:
        return JSONResponse(
            {
                "success": False,
                "message": res.get("message") or "查询失败",
                "data": {"local": local},
            }
        )
    trade = res.get("raw")
    verified = False
    if isinstance(trade, dict):
        try:
            cents = Decimal(str(trade["total_amount"])) * 100
            verified = (
                cents.is_finite()
                and cents == cents.to_integral_value()
                and type(local.get("amount_cents")) is int
                and int(cents) == local["amount_cents"]
                and trade.get("out_trade_no") == out_trade_no
                and str(trade.get("trade_no") or "") == str(local.get("trade_no") or "")
                and trade.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"}
                and local.get("status") in {
                    "paid", "partially_refunded", "refunded", "refund_pending_reconciliation"
                }
            )
        except (InvalidOperation, ValueError, TypeError, KeyError):
            verified = False
    if isinstance(trade, dict) and (
        (trade.get("out_trade_no") and trade["out_trade_no"] != out_trade_no)
        or (
            trade.get("trade_no") and local.get("trade_no")
            and trade["trade_no"] != local["trade_no"]
        )
        or (
            trade.get("total_amount") is not None and type(local.get("amount_cents")) is int
            and not _same_amount_in_cents(trade["total_amount"], local["amount_cents"])
        )
    ):
        return JSONResponse(
            {
                "success": False, "requires_reconciliation": True,
                "message": "支付渠道回查与原订单身份或金额冲突，禁止自动结算",
                "data": {"local": local},
            },
            status_code=409,
        )
    return JSONResponse(
        {
            "success": True,
            "gateway_payment_reconciled": bool(verified),
            "bank_settlement_verified": False,
            "data": {"trade": trade, "local": local},
        }
    )


@router.post("/refund")
def refund_trade(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """Reserve an idempotent refund before the external call.

    API acceptance or timeout is never proof of settlement. A separate
    authenticated gateway query must confirm its original refund identity.
    """
    out_trade_no = str(body.get("out_trade_no") or "").strip()
    refund_amount = str(body.get("refund_amount") or "").strip()
    refund_id = str(body.get("out_request_no") or "").strip() or out_trade_no
    refund_reason = str(body.get("refund_reason") or "").strip() or None
    if not out_trade_no or not refund_amount:
        return JSONResponse(
            {"success": False, "message": "out_trade_no 和 refund_amount 均为必填项"},
            status_code=400,
        )
    try:
        amount = Decimal(refund_amount)
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("refund precision or range invalid")
        cents = int(amount * 100)
    except (InvalidOperation, ValueError):
        return JSONResponse(
            {"success": False, "message": "退款金额必须为正数且最多两位小数"},
            status_code=400,
        )
    # Resolve real owner and live refund privilege before writing the original
    # order record or dispatching anything to the payment provider.
    owned_payment_order(request, out_trade_no, permission="model_payment.refund")
    try:
        reason, attempt = mp_orders.reserve_refund_attempt(
            out_trade_no=out_trade_no, out_request_no=refund_id, amount_cents=cents,
        )
    except (OSError, ValueError):
        logger.exception("[model-payment] refund claim persistence failed")
        return JSONResponse(
            {"success": False, "requires_reconciliation": True},
            status_code=503,
        )
    if reason != "refund_reserved":
        return JSONResponse(
            {
                "success": False,
                "reason_code": reason,
                "requires_reconciliation": reason in {
                    "refund_request_replay", "refund_requires_reconciliation",
                    "refund_order_not_settled", "refund_history_corrupt",
                },
                "message": "原退款状态无法安全重复提交，请先查询渠道退款记录",
            },
            status_code=409,
        )
    # From here on: external side effects may exist even after an exception.
    # Keep the original pending claim; never retry with a fresh request ID.
    try:
        response = mp_ali.refund_order(
            out_trade_no=out_trade_no,
            refund_amount=f"{amount:.2f}",
            out_request_no=refund_id,
            refund_reason=refund_reason,
        )
    except INFRA_TRANSIENT:
        logger.exception("[model-payment] refund provider outcome unknown")
        response = {"success": False, "message": "渠道状态未知"}
    try:
        persisted = mp_orders.observe_refund_provider_result(
            out_trade_no=out_trade_no,
            out_request_no=refund_id,
            provider_reported_success=response.get("success") is True,
        )
    except (OSError, ValueError):
        persisted = False
        logger.exception("[model-payment] refund provider response persistence failed")
    if not persisted:
        return JSONResponse(
            {
                "success": False,
                "requires_reconciliation": True,
                "message": "渠道已调用但原退款回执无法持久核验，禁止重复提交",
            },
            status_code=503,
        )
    return JSONResponse(
        {
            "success": False,
            "accepted": response.get("success") is True,
            "requires_reconciliation": True,
            "refund_request_no": refund_id,
            "message": (
                "渠道受理回执已记录，须再次查询原退款单核验后才记为已退款"
                if response.get("success") is True
                else "渠道结果未知或拒绝，保留原请求待独立查询，禁止重新发起"
            ),
        },
        status_code=202 if response.get("success") is True else 503,
    )


@router.post("/close")
def close_trade(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """alipay.trade.close：关闭未付款交易。body: out_trade_no 或 trade_no。"""
    out_trade_no = str(body.get("out_trade_no") or "").strip() or None
    trade_no = str(body.get("trade_no") or "").strip() or None
    if not out_trade_no:
        return JSONResponse(
            {"success": False, "message": "out_trade_no 必填，不能仅按支付商交易号关闭"},
            status_code=400,
        )

    local = owned_payment_order(request, out_trade_no)
    if trade_no and trade_no != local.get("trade_no"):
        raise HTTPException(status_code=404, detail="订单不存在")
    res = mp_ali.close_order(out_trade_no=out_trade_no, trade_no=None)
    if not res["success"]:
        return JSONResponse({"success": False, "message": res.get("message") or "关闭交易失败"})

    try:
        closed = mp_orders.update_order_status(
            out_trade_no=out_trade_no, status="closed"
        )
    except (OSError, ValueError):
        closed = None
        logger.exception("[model-payment] 渠道关闭成功但本地回执丢失")
    if not isinstance(closed, dict) or closed.get("status") != "closed":
        return JSONResponse(
            {
                "success": False, "requires_reconciliation": True,
                "message": "渠道可能已关闭原交易但本地回执尚未持久核对，禁止重复关闭",
            },
            status_code=503,
        )
    logger.info("[model-payment] close verified locally out_trade_no=%s", out_trade_no)
    return JSONResponse({"success": True, "data": res.get("raw")})


@router.get("/refund/query")
def refund_query(request: Request, out_trade_no: str, out_request_no: str | None = None):
    """Read the original gateway refund and settle only exact confirmed identity."""
    if not out_trade_no:
        return JSONResponse({"success": False, "message": "out_trade_no 必填"}, status_code=400)
    owned_payment_order(request, out_trade_no, permission="model_payment.refund")
    request_no = (out_request_no or "").strip() or out_trade_no
    provider = mp_ali.query_refund(out_trade_no=out_trade_no, out_request_no=request_no)
    raw = provider.get("raw") if isinstance(provider, dict) else None
    if not provider.get("success") or not isinstance(raw, dict):
        return JSONResponse(
            {
                "success": False,
                "requires_reconciliation": True,
                "message": "退款渠道核对暂不可用，原订单仍待核验",
            },
            status_code=503,
        )
    # Never treat an API HTTP 200 or provider code=10000 alone as a refund.
    if (
        str(raw.get("refund_status") or "") != "REFUND_SUCCESS"
        or (raw.get("out_trade_no") and str(raw["out_trade_no"]) != out_trade_no)
        or (raw.get("out_request_no") and str(raw["out_request_no"]) != request_no)
    ):
        return JSONResponse(
            {"success": False, "requires_reconciliation": True, "message": "渠道尚未确认原退款"},
            status_code=409,
        )
    try:
        paid_back = Decimal(str(raw.get("refund_amount")))
        if (
            not paid_back.is_finite()
            or paid_back <= 0
            or paid_back != paid_back.quantize(Decimal("0.01"))
        ):
            raise ValueError("invalid provider amount")
        paid_back_cents = int(paid_back * 100)
        reason, receipt = mp_orders.confirm_refund_from_provider_query(
            out_trade_no=out_trade_no,
            out_request_no=request_no,
            amount_cents=paid_back_cents,
        )
    except (OSError, InvalidOperation, ValueError, TypeError):
        logger.exception("[model-payment] refund provider confirmation persistence failed")
        return JSONResponse(
            {"success": False, "requires_reconciliation": True},
            status_code=503,
        )
    if reason not in {"refund_confirmed", "already_confirmed"}:
        return JSONResponse(
            {
                "success": False, "reason_code": reason, "requires_reconciliation": True,
                "message": "渠道退款金额与原有请求不一致，禁止自动入账",
            },
            status_code=409,
        )
    return JSONResponse(
        {
            "success": True,
            "gateway_refund_confirmed": True,
            "bank_settlement_verified": False,
            "refund_request_no": request_no,
            "receipt": receipt,
        }
    )
