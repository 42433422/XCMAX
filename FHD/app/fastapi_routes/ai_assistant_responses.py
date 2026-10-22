"""Response builders for AI-assistant compatibility routes."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return payload


def fail(message: str, status: int = 400, **extra: Any) -> JSONResponse:
    payload: dict[str, Any] = {"success": False, "message": message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status)


def shipment_failure(result: dict[str, Any]) -> tuple[dict[str, Any], int]:
    from app.domain.shipment.shipment_quantities import shipment_quantity_hint

    code = str(result.get("error_code") or "")[:64]
    hint = shipment_quantity_hint(code)
    return {"success": False, "message": hint or "生成失败", "error_code": code or None}, (
        400 if hint else 500
    )
