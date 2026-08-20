# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


def _checkout_sign_body_from_request(body: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    out: dict[str, _facade().Any] = {}
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


def _checkout_body_has_signature(body: dict[str, _facade().Any]) -> bool:
    return all(bool(body.get(key)) for key in ("request_id", "signature", "timestamp"))


async def _resolve_market_authorization_for_checkout(
    request: _facade().Request, body: dict[str, _facade().Any]
) -> tuple[str, dict[str, _facade().Any] | None]:
    return (await _facade()._authorization_from_request_resolved(request, body), None)


@_facade().router.post("/payment/direct-checkout")
async def market_payment_direct_checkout(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    resolved = await _facade()._resolve_market_authorization_for_checkout(request, body)
    authorization = resolved[0] if isinstance(resolved, tuple) else str(resolved or "")
    if not authorization:
        return _facade().JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    sign_body = _facade()._checkout_sign_body_from_request(body)
    signed = await _facade()._proxy_json(
        "POST",
        "/api/payment/sign-checkout",
        json_body=sign_body,
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(signed, dict) and signed.get("__proxy_error__"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _facade()._error_message(
                    signed.get("payload"), int(signed.get("status_code") or 502)
                ),
            },
            status_code=int(signed.get("status_code") or 502),
        )
    checkout_body = {**body}
    if isinstance(signed, dict):
        checkout_body.update(signed)
    payload = await _facade()._proxy_json(
        "POST",
        "/api/payment/checkout",
        json_body=checkout_body,
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _facade()._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload, "signed": signed}


@_facade().router.get("/payment/orders")
async def market_payment_orders(
    request: _facade().Request, status: str | None = None, limit: int = 50, offset: int = 0
):
    path = f"/api/payment/orders?limit={int(limit)}&offset={int(offset)}"
    if status:
        path += f"&status={status.strip()}"
    payload = await _facade()._proxy_json(
        "GET",
        path,
        authorization=_facade()._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _facade()._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}


@_facade().router.get("/payment/query/{out_trade_no}")
async def market_payment_query(request: _facade().Request, out_trade_no: str):
    payload = await _facade()._proxy_json(
        "GET",
        f"/api/payment/query/{out_trade_no}",
        authorization=_facade()._market_auth_from_request(request),
        return_error_payload=True,
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _facade()._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}


@_facade().router.get("/wallet/overview")
async def market_wallet_overview(request: _facade().Request):
    authorization = await _facade()._authorization_from_request_resolved(request, {})
    if not authorization:
        authorization = _facade()._market_auth_from_request(request)
    if not authorization:
        return _facade().JSONResponse(
            {"success": False, "message": "尚未绑定市场账号；请重新登录软件以自动同步"},
            status_code=401,
        )
    payload = await _facade()._proxy_json(
        "GET", "/api/wallet/overview", authorization=authorization, return_error_payload=True
    )
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        return _facade().JSONResponse(
            {
                "success": False,
                "message": _facade()._error_message(
                    payload.get("payload"), int(payload.get("status_code") or 502)
                ),
            },
            status_code=int(payload.get("status_code") or 502),
        )
    return {"success": True, "data": payload}


@_facade().router.get("/status")
async def market_status():
    """Check whether the local backend can reach the configured Xiuci market server."""
    payload = await _facade()._proxy_json("GET", "/api/health", return_error_payload=True)
    if isinstance(payload, _facade().JSONResponse):
        return payload
    reachable = not (isinstance(payload, dict) and payload.get("__proxy_error__"))
    return {
        "success": reachable,
        "data": {
            "market_base_url": _facade()._market_base_url(),
            "reachable": reachable,
            "raw": payload.get("payload")
            if isinstance(payload, dict) and payload.get("__proxy_error__")
            else payload,
        },
    }


@_facade().router.post("/dev-create-account")
async def market_dev_create_account(
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """Create a market account via server-side open API and verify login/overview connectivity."""
    username = str(body.get("username") or f"xcagi_{_facade().uuid.uuid4().hex[:10]}").strip()
    password = str(body.get("password") or _facade().uuid.uuid4().hex[:12])
    email = str(body.get("email") or f"{username}@xcagi.local").strip()
    if len(password) < 6:
        return _facade().JSONResponse(
            {"success": False, "message": "password 至少 6 位"}, status_code=400
        )
    payload = await _facade()._register_without_verification(username, password, email)
    if isinstance(payload, _facade().JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 400)
        raw_error = payload.get("payload")
        if status_code == 409 or "存在" in _facade()._error_message(raw_error, status_code):
            payload = await _facade()._proxy_json(
                "POST", "/api/auth/login", json_body={"username": username, "password": password}
            )
        else:
            return _facade().JSONResponse(
                {
                    "success": False,
                    "message": _facade()._error_message(raw_error, status_code),
                    "data": raw_error,
                },
                status_code=status_code,
            )
    token = _facade()._token_from_auth_response(payload)
    if not token:
        return _facade().JSONResponse(
            {"success": False, "message": "账号创建成功但未返回 token", "data": payload},
            status_code=502,
        )
    overview = await _facade()._proxy_json(
        "GET", "/api/account/bootstrap", authorization=token, return_error_payload=True
    )
    return {
        "success": True,
        "data": {
            "market_base_url": _facade()._market_base_url(),
            "username": username,
            "email": email,
            "password": password,
            "token": token,
            "overview_ok": not (isinstance(overview, dict) and overview.get("__proxy_error__")),
            "overview": overview.get("payload")
            if isinstance(overview, dict) and overview.get("__proxy_error__")
            else overview,
        },
    }
