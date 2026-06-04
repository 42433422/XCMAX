"""统一计费 API（阶段 11）：报价 / 计量 / 对账。

- ``POST /api/billing/quote``      三套引擎统一报价（订阅 / 买断 / 计量）
- ``POST /api/billing/meter``      记录一条跨宿主计量（路由到统一 SoT）
- ``POST /api/billing/reconcile``  跨宿主对账汇总
- ``GET  /api/billing/backend``    当前计费真相源后端
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/backend")
def billing_backend() -> JSONResponse:
    from app.infrastructure.payment.payment_sot import model_payment_backend

    return JSONResponse({"ok": True, "backend": model_payment_backend()})


@router.post("/quote")
def billing_quote(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """统一报价。Body 需含 ``mode`` 及对应引擎参数。

    示例：
    - 订阅：{"mode":"subscription","plan_price_monthly":29.9,"seats":3,"period":"yearly"}
    - 买断：{"mode":"one_time","unit_price":199,"quantity":2}
    - 计量：{"mode":"usage","units":12000,"tiers":[{"up_to":1000,"price_per_unit":0.01},{"up_to":null,"price_per_unit":0.005}]}
    """
    from app.infrastructure.billing.engines import quote

    mode = str(body.get("mode") or "").strip()
    if not mode:
        return JSONResponse({"ok": False, "message": "缺少 mode"}, status_code=400)
    try:
        params = {k: v for k, v in body.items() if k != "mode"}
        charge = quote(mode, **params)
        return JSONResponse({"ok": True, "charge": charge.as_dict()})
    except Exception as e:
        logger.warning("billing quote failed: %s", e)
        return JSONResponse({"ok": False, "message": str(e)}, status_code=400)


@router.post("/meter")
def billing_meter(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """记录一条计量并路由到统一 SoT。"""
    from app.infrastructure.billing.metering import MeteringRecord, record_usage

    try:
        record = MeteringRecord(
            tenant_id=str(body.get("tenant_id") or "default"),
            sku=str(body.get("sku") or "unknown"),
            mode=str(body.get("mode") or "usage"),
            amount=Decimal(str(body.get("amount") or "0")),
            currency=str(body.get("currency") or "CNY"),
            quantity=float(body.get("quantity") or 1.0),
            idempotency_key=str(body.get("idempotency_key") or ""),
            meta=body.get("meta") or {},
        )
        result = record_usage(record)
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        logger.warning("billing meter failed: %s", e)
        return JSONResponse({"ok": False, "message": str(e)}, status_code=400)


@router.post("/commission")
def billing_commission(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """渠道/代理/OEM 分佣拆分。

    Body: {"gross":1000,"currency":"CNY","partner":{"partner_id":"p1","channel_type":"reseller",
            "commission_rate":0.2,"parent_id":"p0","parent_override_rate":0.05}}
    """
    from app.infrastructure.billing.channels import partner_from_dict, split_commission

    try:
        partner_raw = body.get("partner")
        partner = partner_from_dict(partner_raw) if isinstance(partner_raw, dict) else None
        split = split_commission(
            body.get("gross") or 0, partner=partner, currency=str(body.get("currency") or "CNY")
        )
        return JSONResponse({"ok": True, "split": split.as_dict()})
    except Exception as e:
        logger.warning("billing commission failed: %s", e)
        return JSONResponse({"ok": False, "message": str(e)}, status_code=400)


@router.post("/reconcile")
def billing_reconcile(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """跨宿主对账汇总。Body: {"records":[{tenant_id,sku,mode,amount,...}, ...]}。"""
    from app.infrastructure.billing.metering import MeteringRecord, reconcile

    raw = body.get("records") or []
    records = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            records.append(
                MeteringRecord(
                    tenant_id=str(item.get("tenant_id") or "default"),
                    sku=str(item.get("sku") or "unknown"),
                    mode=str(item.get("mode") or "usage"),
                    amount=Decimal(str(item.get("amount") or "0")),
                    currency=str(item.get("currency") or "CNY"),
                    backend=str(item.get("backend") or ""),
                )
            )
        except Exception:
            continue
    return JSONResponse({"ok": True, **reconcile(records)})
