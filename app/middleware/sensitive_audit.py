# -*- coding: utf-8 -*-
"""
结构化 API 审计日志（JSON Lines）。

设置 ``AUDIT_LOG_PATH`` 后对 /api/* 请求追加审计行；敏感路径额外标注 ``sensitive`` / ``action``。
不记录聊天类接口的请求/响应正文（见 ``ENTERPRISE_AUDIT.md``）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()

# 流式路由后缀（duration 为到响应对象返回前）
_STREAMING_SUFFIXES = ("/stream",)

# 不记录 body 摘要的路径前缀
_BODY_EXCLUDE_PREFIXES = (
    "/api/chat",
    "/api/chat/stream",
)

_SENSITIVE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("auth_login", re.compile(r"^/api/auth/login/?$", re.I)),
    ("auth_logout", re.compile(r"^/api/auth/logout/?$", re.I)),
    ("auth_register", re.compile(r"^/api/auth/register/?$", re.I)),
    ("auth_password_change", re.compile(r"^/api/auth/password/change/?$", re.I)),
    ("auth_password_reset", re.compile(r"^/api/auth/forgot-password/", re.I)),
    ("rbac_mutation", re.compile(r"^/api/rbac/", re.I)),
    ("data_export", re.compile(r"/export(?:\.|/|$)", re.I)),
    ("approval_mutation", re.compile(r"^/api/approval/requests/\d+/(approve|reject|withdraw|delete)", re.I)),
    ("mod_install", re.compile(r"^/api/mods/(install|uninstall|upgrade)", re.I)),
    ("db_token", re.compile(r"^/api/fhd/db-tokens/", re.I)),
]


def _audit_log_path() -> str:
    return (os.environ.get("AUDIT_LOG_PATH") or "").strip()


def _audit_sensitive_only() -> bool:
    return (os.environ.get("AUDIT_SENSITIVE_ONLY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _client_host(request: Request) -> str:
    from app.http.client_ip import client_host_from_request

    return client_host_from_request(request)


def _classify_sensitive(method: str, path: str) -> tuple[bool, str | None]:
    m = (method or "GET").upper()
    for action, pattern in _SENSITIVE_RULES:
        if pattern.search(path):
            return True, action
    if m == "DELETE" and path.startswith("/api/"):
        return True, "http_delete"
    if m in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/rbac/"):
        return True, "rbac_mutation"
    return False, None


def _is_streaming_path(path: str) -> bool:
    return any(path.rstrip("/").endswith(sfx.rstrip("/")) for sfx in _STREAMING_SUFFIXES)


def _should_audit_path(path: str, sensitive: bool) -> bool:
    if not path.startswith("/api/"):
        return False
    if path.startswith(("/api/health", "/api/system/health")):
        return False
    if _audit_sensitive_only():
        return sensitive
    return True


def _append_audit_line(path: str, record: dict[str, Any]) -> None:
    audit_path = _audit_log_path()
    if not audit_path:
        return
    try:
        parent = os.path.dirname(audit_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _WRITE_LOCK:
            with open(audit_path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:
        logger.debug("audit append failed path=%s: %s", path, exc)


def _actor_from_request(request: Request) -> str | None:
    val = (request.headers.get("x-user-id") or request.headers.get("X-User-ID") or "").strip()
    if val:
        return val[:64]
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return "<bearer>"
    return None


class SensitiveAuditMiddleware(BaseHTTPMiddleware):
    """可选 JSON Lines 审计：全量 /api 或仅敏感操作（AUDIT_SENSITIVE_ONLY）。"""

    async def dispatch(self, request: Request, call_next):
        audit_path = _audit_log_path()
        if not audit_path:
            return await call_next(request)

        path = request.url.path or ""
        method = request.method or "GET"
        sensitive, action = _classify_sensitive(method, path)
        if not _should_audit_path(path, sensitive):
            return await call_next(request)

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = int(response.status_code)
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            request_id = getattr(request.state, "request_id", None) or (
                request.headers.get("x-request-id") or ""
            ).strip()
            ua = (request.headers.get("user-agent") or "")[:512]
            record: dict[str, Any] = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id or None,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "streaming": _is_streaming_path(path),
                "client_host": _client_host(request),
                "user_agent": ua,
            }
            if sensitive:
                record["sensitive"] = True
                if action:
                    record["action"] = action
            actor = _actor_from_request(request)
            if actor:
                record["actor"] = actor
            if any(path.startswith(p) for p in _BODY_EXCLUDE_PREFIXES):
                record["body_redacted"] = True
            _append_audit_line(audit_path, record)
