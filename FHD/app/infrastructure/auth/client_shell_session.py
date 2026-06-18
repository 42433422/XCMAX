"""企业端 (:5001) 与管理端 (:5011) 会话 Cookie 隔离。

同机开发时 ``127.0.0.1`` 不按端口区分 Cookie，若共用 ``session_id`` 会串登录态。
前端随请求附带 ``X-XCMAX-Client-Shell: enterprise|admin``，后端读写对应 Cookie。
"""

from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import Response

CLIENT_SHELL_HEADER = "X-XCMAX-Client-Shell"
ADMIN_SHELL = "admin"
ENTERPRISE_SHELL = "enterprise"


def client_shell_from_request(request: Request) -> str:
    raw = str(request.headers.get(CLIENT_SHELL_HEADER) or "").strip().lower()
    if raw == ADMIN_SHELL:
        return ADMIN_SHELL
    if raw in (ENTERPRISE_SHELL, "enterprise", "desktop", "web"):
        return ENTERPRISE_SHELL
    referer = str(request.headers.get("referer") or "").lower()
    if ":5011/admin" in referer or referer.rstrip("/").endswith(":5011/admin"):
        return ADMIN_SHELL
    return ENTERPRISE_SHELL


def session_cookie_name_for_shell(shell: str) -> str:
    if shell == ADMIN_SHELL:
        return (os.environ.get("ADMIN_SESSION_COOKIE_NAME") or "admin_session_id").strip()
    return (os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()


def session_cookie_name_for_request(request: Request) -> str:
    return session_cookie_name_for_shell(client_shell_from_request(request))


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
    "client_shell_from_request",
    "resolve_session_id_from_request",
    "session_cookie_name_for_request",
    "session_cookie_name_for_shell",
]
