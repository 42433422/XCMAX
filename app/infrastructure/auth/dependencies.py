"""
FastAPI 依赖函数：用于敏感路由的身份/令牌校验。

当前实现为轻量"软校验"层：
- 读取 `X-User-ID` 请求头作为用户 ID（与审批模块保持一致）
- 对写操作路由（导出/删除/审批）可选地要求 DB 写令牌
- 不强制身份验证（兼容未登录的桌面模式）；强制检查由各路由按需开启

Phase 计划：等待正式会话/JWT 层就绪后，替换为标准 OAuth2 Bearer 校验。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Header, HTTPException, Request


def _write_lock_enabled() -> bool:
    v = (os.environ.get("FHD_DISABLE_DB_WRITE_LOCK") or "").strip().lower()
    return v not in {"1", "true", "yes", "on"}


class CurrentUser:
    """简化用户上下文（现阶段以 user_id 为主要标识符）。"""

    def __init__(self, user_id: int | None, raw_header: str | None = None):
        self.user_id = user_id
        self.raw_header = raw_header

    @property
    def is_identified(self) -> bool:
        return self.user_id is not None

    def __repr__(self) -> str:
        return f"CurrentUser(user_id={self.user_id})"


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> CurrentUser:
    """
    FastAPI `Depends` 工厂：从 X-User-ID 请求头解析当前用户。

    使用方式：
        @router.delete("/api/shipment/records/{id}")
        def delete_record(user: CurrentUser = Depends(get_current_user)):
            ...
    """
    uid: int | None = None
    if x_user_id and str(x_user_id).strip().lstrip("-").isdigit():
        try:
            uid = int(str(x_user_id).strip())
        except (TypeError, ValueError):
            uid = None
    return CurrentUser(user_id=uid, raw_header=x_user_id)


def require_identified_user(
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> CurrentUser:
    """严格版：若未提供合法 X-User-ID 则返回 401。用于高敏感操作（如删除审批流程）。"""
    from fastapi import HTTPException

    user = get_current_user(x_user_id=x_user_id)
    if not user.is_identified and _write_lock_enabled():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "user_id_required",
                "message": "此操作需要提供 X-User-ID 请求头以记录操作人。",
            },
        )
    return user


def session_id_from_request(request: Request) -> str | None:
    """从 Authorization Bearer 或 session cookie 解析会话 ID。"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token or None
    from app.config import Config

    cookie_name = getattr(Config, "SESSION_COOKIE_NAME", "session_id")
    sid = request.cookies.get(cookie_name)
    return str(sid).strip() if sid else None


def resolve_session_user(request: Request) -> Any | None:
    """解析当前请求关联的 User，未登录返回 None。"""
    sid = session_id_from_request(request)
    if not sid:
        return None
    from app.services import get_session_service

    return get_session_service().validate_session(sid)


def get_logged_in_user(request: Request) -> Any:
    """FastAPI Depends：要求有效会话，否则 401。"""
    user = resolve_session_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "message": {
                    "code": "UNAUTHORIZED",
                    "message": "请先登录",
                },
            },
        )
    if not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=403,
            detail={
                "message": {
                    "code": "ACCOUNT_DISABLED",
                    "message": "账户已被禁用",
                },
            },
        )
    return user


def require_permission(permission_code: str) -> Callable[..., Any]:
    """FastAPI Depends 工厂：校验 RBAC 权限码。"""

    def _check(user: Any = Depends(get_logged_in_user)) -> Any:
        from app.application.facades.session_facade import get_auth_service
        from app.infrastructure.auth.enterprise_roles import role_has_permission

        if role_has_permission(getattr(user, "role", None), permission_code):
            return user
        auth_service = get_auth_service()
        if not auth_service.has_permission(user, permission_code):
            raise HTTPException(
                status_code=403,
                detail={
                    "message": {
                        "code": "FORBIDDEN",
                        "message": "权限不足",
                    },
                },
            )
        return user

    return _check


__all__ = [
    "CurrentUser",
    "get_current_user",
    "require_identified_user",
    "session_id_from_request",
    "resolve_session_user",
    "get_logged_in_user",
    "require_permission",
]
