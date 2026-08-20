# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


@_facade().router.post("/admin/impersonate/activate-enterprise", response_model=None)
async def admin_activate_enterprise_impersonation(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    from app.application.impersonation_bridge import (
        consume_impersonation_bridge_token,
        mirror_admin_impersonation_to_enterprise_session,
    )
    from app.config import Config

    token = str(body.get("bridge_token") or body.get("token") or "").strip()
    if not token:
        return _facade().JSONResponse(
            {"success": False, "message": "bridge_token 必填"}, status_code=400
        )
    admin_sid = consume_impersonation_bridge_token(token)
    if not admin_sid:
        return _facade().JSONResponse(
            {"success": False, "message": "bridge_token 无效或已过期"}, status_code=400
        )
    enterprise_sid = str(
        body.get("enterprise_session_id")
        or request.cookies.get(getattr(Config, "SESSION_COOKIE_NAME", "session_id"))
        or ""
    ).strip()
    try:
        sid = mirror_admin_impersonation_to_enterprise_session(admin_sid, enterprise_sid or None)
    except ValueError as exc:
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    return {"success": True, "session_id": sid}
