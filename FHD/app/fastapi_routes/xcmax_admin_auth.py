"""Shared authenticated-admin gate and audit actor resolution."""

from __future__ import annotations

import hashlib

from fastapi import Request
from fastapi.responses import JSONResponse


def require_market_admin_session(request: Request) -> JSONResponse | None:
    from app.application.desktop_admin_gate import (
        assert_desktop_allows_session,
        forbidden_payload,
        is_desktop_runtime,
    )
    from app.application.session_account_meta import load_session_account_meta
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if is_desktop_runtime():
        return JSONResponse(forbidden_payload(), status_code=403)

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    meta = load_session_account_meta(sid) or {}
    denied = assert_desktop_allows_session(meta, session_id=sid)
    if denied is not None:
        return JSONResponse(denied, status_code=403)
    if meta.get("account_kind") != "admin" or not meta.get("market_is_admin"):
        return JSONResponse(
            {"success": False, "message": "需要管理员账号登录后访问"},
            status_code=403,
        )
    return None


def admin_approver_from_session(request: Request) -> str:
    """Return an auditable actor derived only from the authenticated session."""

    from app.application.session_account_meta import load_session_account_meta
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    meta = load_session_account_meta(sid) if sid else {}
    for key in ("username", "market_username", "display_name"):
        value = str((meta or {}).get(key) or "").strip()
        if value:
            return value
    for key, prefix in (
        ("market_user_id", "market-admin"),
        ("local_user_id", "local-admin"),
    ):
        value = str((meta or {}).get(key) or "").strip()
        if value:
            return f"{prefix}:{value}"
    if sid:
        digest = hashlib.sha256(str(sid).encode("utf-8")).hexdigest()[:12]
        return f"admin-session:{digest}"
    return ""


__all__ = ["admin_approver_from_session", "require_market_admin_session"]
