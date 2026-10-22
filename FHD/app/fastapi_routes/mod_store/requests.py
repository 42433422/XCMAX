"""JSON/form compatibility for Mod store commands."""

from __future__ import annotations

from fastapi import Request

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .projection import safe_text


async def body_value(request: Request, key: str, default: str = "") -> str:
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            data = await request.json()
            if isinstance(data, dict):
                return safe_text(data.get(key) or default)
            return default
        form = await request.form()
        return safe_text(form.get(key) or default)
    except RECOVERABLE_ERRORS:
        return default


async def request_payload(request: Request) -> dict[str, str]:
    content_type = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            data = await request.json()
            return {str(k): safe_text(v) for k, v in data.items()} if isinstance(data, dict) else {}
        form = await request.form()
        return {str(k): safe_text(v) for k, v in form.items()}
    except RECOVERABLE_ERRORS:
        return {}
