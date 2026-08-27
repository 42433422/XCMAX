"""
ASGI 中间件：网段白名单。

放在 CORS 后、业务中间件前。命中白名单才放行；否则直接 403。
对预检 OPTIONS、配置的 bypass 路径 / 静态资源前缀放行，避免误伤健康检查
和登录页本身。
"""

from __future__ import annotations

import json
import logging
from ipaddress import ip_address

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.security.lan_config import get_lan_config, lan_guard_path_is_bypassed
from app.security.lan_ip import get_client_ip
from app.security.license_store import is_ip_explicitly_allowed, touch_allowed_client
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _scope_host(scope: Scope) -> str:
    """Return a normalized HTTP host without trusting forwarded headers."""

    for raw_name, raw_value in scope.get("headers") or []:
        try:
            name = raw_name.decode("latin-1") if isinstance(raw_name, bytes) else str(raw_name)
        except RECOVERABLE_ERRORS:
            continue
        if name.lower() != "host":
            continue
        try:
            value = raw_value.decode("latin-1") if isinstance(raw_value, bytes) else str(raw_value)
        except RECOVERABLE_ERRORS:
            return ""
        value = value.strip().lower()
        if value.startswith("["):
            return value.split("]", 1)[0].lstrip("[")
        return value.split(":", 1)[0]
    return ""


def _authenticated_public_admin(scope: Scope, cfg) -> bool:
    """Fail closed unless this is a live market-admin session on an allowlisted host.

    The public management console deliberately shares the FHD API process with
    LAN-only ERP routes.  A valid administrator session may cross only this
    network gate; every route's normal authentication/authorization still runs
    afterwards.
    """

    host = _scope_host(scope)
    allowed_hosts = {str(item).strip().lower() for item in cfg.public_admin_hosts if item}
    if not host or host not in allowed_hosts:
        return False

    path = str(scope.get("path") or "/")
    if path.startswith("/fhd-api/"):
        path = path.removeprefix("/fhd-api") or "/"
    if not (path.startswith("/api/") or path.startswith("/ws/")):
        return False

    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.infrastructure.auth.dependencies import (
            resolve_session_user,
            session_id_from_request,
        )

        request = Request(scope)
        session_id = session_id_from_request(request)
        if not session_id:
            return False
        user = resolve_session_user(request)
        if user is None or not bool(getattr(user, "is_active", True)):
            return False
        meta = load_session_account_meta(session_id) or {}
        return bool(meta.get("account_kind") == "admin" and meta.get("market_is_admin"))
    except RECOVERABLE_ERRORS:
        logger.warning(
            "public admin session validation failed: host=%s path=%s",
            host,
            path,
            exc_info=True,
        )
        return False


def _ip_in_cidrs(ip: str, cidrs) -> bool:
    if not ip:
        return False
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    for net in cidrs:
        try:
            if addr in net:
                return True
        except (TypeError, ValueError):
            continue
    return False


async def _send_json(send: Send, status: int, body: dict) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"x-lan-guard", b"cidr-blocked"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


class LanCidrGuard:
    """ASGI 中间件：在管道最外层做网段过滤。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        cfg = get_lan_config()
        if not cfg.enabled:
            await self.app(scope, receive, send)
            return

        method = (scope.get("method") or "GET").upper()
        path = scope.get("path") or "/"

        if method == "OPTIONS" or lan_guard_path_is_bypassed(path, cfg):
            await self.app(scope, receive, send)
            return

        cidrs = cfg.cidr_objects()
        if not cidrs:
            await self.app(scope, receive, send)
            return

        client_ip = get_client_ip(scope, cfg.trusted_proxies)
        if _ip_in_cidrs(client_ip or "", cidrs) or is_ip_explicitly_allowed(client_ip or ""):
            scope.setdefault("state", {})
            try:
                scope["state"]["lan_client_ip"] = client_ip
            except RECOVERABLE_ERRORS:
                pass
            try:
                touch_allowed_client(client_ip or "")
            except RECOVERABLE_ERRORS:
                logger.debug("touch_allowed_client failed for ip=%s", client_ip, exc_info=True)
            await self.app(scope, receive, send)
            return

        if _authenticated_public_admin(scope, cfg):
            scope.setdefault("state", {})
            try:
                scope["state"]["lan_public_admin_session"] = True
                scope["state"]["lan_is_admin"] = True
                scope["state"]["lan_client_ip"] = client_ip
            except RECOVERABLE_ERRORS:
                pass
            await self.app(scope, receive, send)
            return

        logger.warning("LAN CIDR blocked: ip=%s path=%s", client_ip, path)
        await _send_json(
            send,
            403,
            {
                "success": False,
                "error": "lan_blocked",
                "message": "访问被局域网模式拒绝：当前 IP 不在白名单网段内",
                "ip": client_ip,
            },
        )
