"""从会话解析当前租户 ID（RBAC / IM 隔离）。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.infrastructure.auth.dependencies import session_id_from_request


def resolve_tenant_id(request: Request) -> int | None:
    """从 Cookie session → user.tenant_id；admin 平台账号可为空。"""
    sid = session_id_from_request(request)
    if not sid:
        return None
    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.application.facades.session_facade import get_session_service

        meta = load_session_account_meta(sid) or {}
        session_tenant = meta.get("tenant_id")
        if session_tenant is not None:
            return int(session_tenant)

        user = get_session_service().validate_session(sid)
        if user is None:
            return None
        tid = getattr(user, "tenant_id", None)
        return int(tid) if tid is not None else None
    except Exception:
        return None


def tenant_id_for_user(user: Any) -> int | None:
    tid = getattr(user, "tenant_id", None)
    return int(tid) if tid is not None else None
