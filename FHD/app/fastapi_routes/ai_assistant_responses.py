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
