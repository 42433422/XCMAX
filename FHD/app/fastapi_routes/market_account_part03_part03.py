# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


@_facade().router.post("/payment/checkout")
async def market_payment_checkout(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    payload = await _facade()._proxy_json(
        "POST",
        "/api/payment/checkout",
        json_body=body,
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
