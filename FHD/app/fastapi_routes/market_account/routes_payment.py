"""Market payment routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.market_account._patch as _p

router = APIRouter()

def _market_auth_from_request(request: Request) -> str:
    sid = _p.session_id_from_request(request)
    tok = _p.session_market_token(sid)
    if tok:
        return tok
    return str(request.headers.get("Authorization") or "").strip()
def _checkout_sign_body_from_request(body: dict[str, Any]) -> dict[str, Any]:
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
def _checkout_body_has_signature(body: dict[str, Any]) -> bool:
    return all(bool(body.get(key)) for key in ("request_id", "signature", "timestamp"))
async def _resolve_market_authorization_for_checkout(
    request: Request, body: dict[str, Any]
) -> tuple[str, dict[str, Any] | None]:
    return await _p._authorization_from_request_resolved(request, body), None
@router.get("/payment/plans")
async def market_payment_plans(request: Request):
    """修茈市场套餐（含微信/支付宝统一收银，Java SoT）。"""
    payload = await _p._proxy_json(
        "GET",
        "/api/payment/plans",
        authorization=_p._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload, "market_base_url": _p._market_base_url()}

@router.post("/payment/checkout")
async def market_payment_checkout(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    payload = await _p._proxy_json(
        "POST",
        "/api/payment/checkout",
        json_body=body,
        authorization=_p._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}

@router.post("/payment/direct-checkout")
async def market_payment_direct_checkout(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    resolved = await _p._resolve_market_authorization_for_checkout(request, body)
    authorization = resolved[0] if isinstance(resolved, tuple) else str(resolved or "")
    if not authorization:
        return JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    sign_body = _p._checkout_sign_body_from_request(body)
    signed = await _p._proxy_json(
        "POST",
        "/api/payment/sign-checkout",
        json_body=sign_body,
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(signed, dict) and signed.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    signed.get("payload"), int(signed.get("status_code") or 502)
                ),
            },
            status_code=int(signed.get("status_code") or 502),
        )
    checkout_body = {**body}
    if isinstance(signed, dict):
        checkout_body.update(signed)
    payload = await _p._proxy_json(
        "POST",
        "/api/payment/checkout",
        json_body=checkout_body,
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload, "signed": signed}

@router.get("/payment/orders")
async def market_payment_orders(
    request: Request,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    path = f"/api/payment/orders?limit={int(limit)}&offset={int(offset)}"
    if status:
        path += f"&status={status.strip()}"
    payload = await _p._proxy_json(
        "GET",
        path,
        authorization=_p._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}

@router.get("/payment/query/{out_trade_no}")
async def market_payment_query(request: Request, out_trade_no: str):
    payload = await _p._proxy_json(
        "GET",
        f"/api/payment/query/{out_trade_no}",
        authorization=_p._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}

@router.get("/wallet/overview")
async def market_wallet_overview(request: Request):
    payload = await _p._proxy_json(
        "GET",
        "/api/wallet/overview",
        authorization=_p._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return JSONResponse(
            {
                "success": False,
                "message": _p._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}
