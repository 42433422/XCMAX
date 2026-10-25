"""Canonical payment orchestration and a shared upstream error translation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.market_bridge.protocols import (
    CheckoutAuthorization,
    JsonObject,
    ProxyJSON,
    RequestAuthorization,
)


def _checkout_sign_body_from_request(body: JsonObject) -> JsonObject:
    out: JsonObject = {}
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


def _checkout_body_has_signature(body: JsonObject) -> bool:
    return all(bool(body.get(key)) for key in ("request_id", "signature", "timestamp"))


@dataclass
class Payments:
    proxy: ProxyJSON
    error_message: Callable[[Any, int], str]
    base_url: Callable[[], str]
    request_auth: Callable[[Request], str]
    resolved_auth: RequestAuthorization
    checkout_auth: CheckoutAuthorization
    sign_body: Callable[[JsonObject], JsonObject]

    def error_response(self, payload: Any) -> JSONResponse | None:
        if not isinstance(payload, dict) or not payload.get("__proxy_error__"):
            return None
        status = int(payload.get("status_code") or 502)
        return JSONResponse(
            {"success": False, "message": self.error_message(payload.get("payload"), status)},
            status_code=status,
        )

    def response(self, payload: Any, **extra: Any) -> JsonObject | JSONResponse:
        error = self.error_response(payload)
        return error if error is not None else {"success": True, "data": payload, **extra}

    async def plans(self, request: Request) -> JsonObject | JSONResponse:
        payload = await self.proxy(
            "GET",
            "/api/payment/plans",
            authorization=self.request_auth(request),
            return_error_payload=True,
        )
        error = self.error_response(payload)
        if error is not None:
            return error
        return {"success": True, "data": payload, "market_base_url": self.base_url()}

    async def checkout(self, request: Request, body: JsonObject) -> JsonObject | JSONResponse:
        payload = await self.proxy(
            "POST",
            "/api/payment/checkout",
            json_body=body,
            authorization=self.request_auth(request),
            return_error_payload=True,
        )
        return self.response(payload)

    async def direct_checkout(
        self, request: Request, body: JsonObject
    ) -> JsonObject | JSONResponse:
        resolved = await self.checkout_auth(request, body)
        authorization = resolved[0] if isinstance(resolved, tuple) else str(resolved or "")
        if not authorization:
            return JSONResponse(
                {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
                status_code=401,
            )
        signed = await self.proxy(
            "POST",
            "/api/payment/sign-checkout",
            json_body=self.sign_body(body),
            authorization=authorization,
            return_error_payload=True,
        )
        error = self.error_response(signed)
        if error is not None:
            return error
        checkout_body = dict(body)
        if isinstance(signed, dict):
            checkout_body.update(signed)
        payload = await self.proxy(
            "POST",
            "/api/payment/checkout",
            json_body=checkout_body,
            authorization=authorization,
            return_error_payload=True,
        )
        return self.response(payload, signed=signed)

    async def orders(
        self, request: Request, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> JsonObject | JSONResponse:
        path = f"/api/payment/orders?limit={int(limit)}&offset={int(offset)}"
        if status:
            path += f"&status={status.strip()}"
        payload = await self.proxy(
            "GET", path, authorization=self.request_auth(request), return_error_payload=True
        )
        return self.response(payload)

    async def query(self, request: Request, out_trade_no: str) -> JsonObject | JSONResponse:
        payload = await self.proxy(
            "GET",
            f"/api/payment/query/{out_trade_no}",
            authorization=self.request_auth(request),
            return_error_payload=True,
        )
        return self.response(payload)

    async def wallet(self, request: Request) -> JsonObject | JSONResponse:
        authorization = await self.resolved_auth(request, {})
        if not authorization:
            authorization = self.request_auth(request)
        if not authorization:
            return JSONResponse(
                {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
                status_code=401,
            )
        payload = await self.proxy(
            "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
        )
        return self.response(payload)
