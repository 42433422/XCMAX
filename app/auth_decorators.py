from __future__ import annotations

from contextvars import ContextVar, Token
from functools import wraps
from typing import Any, Callable, List, Optional

from app.config import Config
from app.db.models import User
from app.http.json_response import json_response
from app.services import get_auth_service, get_session_service

_session_service = None
_auth_service = None

_current_user_ctx: ContextVar[Optional[User]] = ContextVar("current_user", default=None)
_session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)


def _get_session_service():
    global _session_service
    if _session_service is None:
        _session_service = get_session_service()
    return _session_service


def _get_auth_service():
    global _auth_service
    if _auth_service is None:
        _auth_service = get_auth_service()
    return _auth_service


def get_current_user() -> Optional[User]:
    return _current_user_ctx.get()


def get_current_session_id() -> Optional[str]:
    return _session_id_ctx.get()


def _extract_session_id() -> Optional[str]:
    from app.http.request_context import get_current_http_request

    req = get_current_http_request()
    if req is None:
        return None
    auth_header = req.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    cookie_name = getattr(Config, "SESSION_COOKIE_NAME", "session_id")
    return req.cookies.get(cookie_name)


def login_required(f: Callable) -> Callable:
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any):
        session_id = _extract_session_id()
        if not session_id:
            return json_response(
                {
                    "success": False,
                    "message": {"code": "UNAUTHORIZED", "message": "请先登录"},
                },
                401,
            ), 401

        session_service = _get_session_service()
        user = session_service.validate_session(session_id)
        if not user:
            return json_response(
                {
                    "success": False,
                    "message": {"code": "SESSION_EXPIRED", "message": "会话已过期，请重新登录"},
                },
                401,
            ), 401

        if not user.is_active:
            return json_response(
                {
                    "success": False,
                    "message": {"code": "ACCOUNT_DISABLED", "message": "账户已被禁用"},
                },
                403,
            ), 403

        t_user: Token[Optional[User]] = _current_user_ctx.set(user)
        t_sid: Token[Optional[str]] = _session_id_ctx.set(session_id)
        try:
            return f(*args, **kwargs)
        finally:
            _current_user_ctx.reset(t_user)
            _session_id_ctx.reset(t_sid)

    return decorated_function


def role_required(roles: List[str]) -> Callable:
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any):
            user = get_current_user()
            if not user:
                return json_response(
                    {
                        "success": False,
                        "message": {"code": "UNAUTHORIZED", "message": "请先登录"},
                    },
                    401,
                ), 401

            if user.role not in roles and user.role != "admin":
                return json_response(
                    {
                        "success": False,
                        "message": {"code": "FORBIDDEN", "message": "权限不足"},
                    },
                    403,
                ), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def permission_required(permission_code: str) -> Callable:
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any):
            user = get_current_user()
            if not user:
                return json_response(
                    {
                        "success": False,
                        "message": {"code": "UNAUTHORIZED", "message": "请先登录"},
                    },
                    401,
                ), 401

            auth_service = _get_auth_service()
            if not auth_service.has_permission(user, permission_code):
                return json_response(
                    {
                        "success": False,
                        "message": {"code": "FORBIDDEN", "message": "权限不足"},
                    },
                    403,
                ), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator
