"""企业端 (:5001 / 桌面) 与管理端 (:5011 /admin) 会话 Cookie 隔离。

同机开发时 ``127.0.0.1`` 不按端口区分 Cookie，若共用 ``session_id`` 会串登录态。
前端随请求附带 ``X-XCMAX-Client-Shell: enterprise|admin``，后端读写对应 Cookie：

- 管理端 → ``admin_session_id``
- 企业端 / 桌面 → ``session_id``
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import Response

CLIENT_SHELL_HEADER = "X-XCMAX-Client-Shell"
ADMIN_SHELL = "admin"
ENTERPRISE_SHELL = "enterprise"


def _header_get(headers: Mapping[str, Any] | None, *names: str) -> str:
    if not headers:
        return ""
    # Starlette Headers 大小写不敏感；dict 兜底按小写比对
    lower_map: dict[str, Any] | None = None
    for name in names:
        try:
            val = headers.get(name)
        except (TypeError, AttributeError, KeyError):
            val = None
        if val is None and not hasattr(headers, "get"):
            return ""
        if val is None:
            if lower_map is None:
                try:
                    lower_map = {str(k).lower(): v for k, v in headers.items()}
                except (TypeError, AttributeError, KeyError):
                    lower_map = {}
            val = lower_map.get(name.lower())
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def client_shell_from_headers(headers: Mapping[str, Any] | None) -> str:
    """从 HTTP / WebSocket 头判定客户端壳（不依赖完整 Request）。"""
    raw = _header_get(headers, CLIENT_SHELL_HEADER, "x-xcmax-client-shell").lower()
    if raw == ADMIN_SHELL:
        return ADMIN_SHELL
    if raw in (ENTERPRISE_SHELL, "enterprise", "desktop", "web"):
        return ENTERPRISE_SHELL

    referer = _header_get(headers, "referer", "Referer").lower()
    origin = _header_get(headers, "origin", "Origin").lower()
    xfh = _header_get(headers, "x-forwarded-host", "X-Forwarded-Host").lower()
    # Vite changeOrigin 后 Host 常被改成后端；优先看转发前 Host / Origin / Referer
    if (
        ":5011/admin" in referer
        or referer.rstrip("/").endswith(":5011/admin")
        or "/admin/login" in referer
        or "/admin/" in referer
        or ":5011" in origin
        or ":5011" in xfh
        or xfh.endswith(":5011")
    ):
        return ADMIN_SHELL
    return ENTERPRISE_SHELL


def client_shell_from_request(request: Request) -> str:
    return client_shell_from_headers(getattr(request, "headers", None))


def session_cookie_name_for_shell(shell: str) -> str:
    if shell == ADMIN_SHELL:
        return (os.environ.get("ADMIN_SESSION_COOKIE_NAME") or "admin_session_id").strip()
    return (os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()


def session_cookie_name_for_request(request: Request) -> str:
    return session_cookie_name_for_shell(client_shell_from_request(request))


def session_cookie_name_from_headers(headers: Mapping[str, Any] | None) -> str:
    return session_cookie_name_for_shell(client_shell_from_headers(headers))


def _allow_bearer_as_session_id() -> bool:
    return os.environ.get("FHD_ALLOW_BEARER_AS_SESSION_ID", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def resolve_session_id_from_request(request: Request) -> str:
    cookie_name = session_cookie_name_for_request(request)
    sid = str(request.cookies.get(cookie_name) or request.headers.get("X-Session-ID") or "").strip()
    if sid:
        return sid
    auth = str(request.headers.get("Authorization") or "")
    if auth.startswith("Bearer ") and _allow_bearer_as_session_id():
        return auth[7:].strip()
    return ""


def attach_session_cookie(
    response: Response,
    session_id: str | None,
    request: Request,
) -> Response:
    sid = (session_id or "").strip()
    if not sid:
        return response
    cookie_name = session_cookie_name_for_request(request)
    max_age = int(os.environ.get("SESSION_COOKIE_MAX_AGE", "315360000"))
    response.set_cookie(
        key=cookie_name,
        value=sid,
        max_age=max_age,
        httponly=os.environ.get("SESSION_COOKIE_HTTPONLY", "1") not in ("0", "false", "False"),
        secure=os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
        samesite=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
        path="/",
    )
    return response


def clear_session_cookie(response: Response, request: Request) -> Response:
    cookie_name = session_cookie_name_for_request(request)
    response.delete_cookie(cookie_name, path="/")
    return response


__all__ = [
    "ADMIN_SHELL",
    "CLIENT_SHELL_HEADER",
    "ENTERPRISE_SHELL",
    "attach_session_cookie",
    "clear_session_cookie",
    "client_shell_from_headers",
    "client_shell_from_request",
    "resolve_session_id_from_request",
    "session_cookie_name_for_request",
    "session_cookie_name_for_shell",
    "session_cookie_name_from_headers",
]
