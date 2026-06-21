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

from fastapi import Header, HTTPException, Request


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
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> CurrentUser:
    """
    FastAPI `Depends` 工厂：优先从登录会话解析用户；测试模式可回退 X-User-ID。
    """
    user = resolve_session_user(request)
    if user is not None and getattr(user, "id", None) is not None:
        return CurrentUser(user_id=int(user.id), raw_header=x_user_id)
    if _allow_x_user_id_header():
        uid: int | None = None
        if x_user_id and str(x_user_id).strip().lstrip("-").isdigit():
            try:
                uid = int(str(x_user_id).strip())
            except (TypeError, ValueError):
                uid = None
        return CurrentUser(user_id=uid, raw_header=x_user_id)
    return CurrentUser(user_id=None, raw_header=x_user_id)


def _allow_x_user_id_header() -> bool:
    return os.environ.get("FHD_ALLOW_X_USER_ID_HEADER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def require_identified_user(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> CurrentUser:
    """严格版：若未提供合法会话用户则返回 401。"""
    user = get_current_user(request, x_user_id=x_user_id)
    if not user.is_identified and _write_lock_enabled():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "user_id_required",
                "message": "请先登录后再执行此操作。",
            },
        )
    return user


def session_id_from_request(request: Request) -> str:
    auth_raw = request.headers.get("Authorization") or ""
    auth = auth_raw if isinstance(auth_raw, str) else ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie_name = (os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()
    cookie_raw = request.cookies.get(cookie_name) or ""
    return cookie_raw.strip() if isinstance(cookie_raw, str) else ""


def resolve_session_user(request: Request) -> Any | None:
    from app.application.facades.session_facade import get_session_service

    sid = session_id_from_request(request)
    if not sid:
        return None
    user = get_session_service().validate_session(sid)
    if user is not None:
        return user
    # 增量无状态 JWT（XCAGI_WEB_JWT_AUTH=1 时）：Bearer 非有效 session 时尝试 web JWT 验签。
    # 默认关 → 现有有状态 session 行为零变化。
    try:
        from app.security.web_jwt import resolve_user_from_web_jwt
    except ImportError:
        return None
    return resolve_user_from_web_jwt(sid)


def get_logged_in_user(request: Request) -> Any:
    user = resolve_session_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "message": {"code": "UNAUTHORIZED", "message": "请先登录"},
            },
        )
    if not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "message": {"code": "ACCOUNT_DISABLED", "message": "账户已被禁用"},
            },
        )
    return user


def require_permission(permission_code: str) -> Callable[..., Any]:
    def _dependency(request: Request) -> Any:
        user = get_logged_in_user(request)
        from app.application.facades.session_facade import get_auth_service

        if not get_auth_service().has_permission(user, permission_code):
            raise HTTPException(
                status_code=403,
                detail={
                    "success": False,
                    "message": {"code": "FORBIDDEN", "message": "权限不足"},
                },
            )
        return user

    return _dependency


def require_admin_user(request: Request) -> Any:
    """要求当前登录用户 tier == "admin"，否则返回 403。

    用于行业切换等仅限管理端操作的敏感路由。
    """
    user = get_logged_in_user(request)
    tier = str(getattr(user, "tier", "") or "").strip()
    if tier != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "success": False,
                "message": {
                    "code": "ADMIN_ONLY",
                    "message": "仅管理端账号可执行此操作",
                },
            },
        )
    return user
