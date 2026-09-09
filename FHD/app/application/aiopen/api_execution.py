"""Authenticated in-process API requests with explicit tenant and Mod scope."""

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from typing import Any
from urllib.parse import unquote, urlsplit

from starlette.requests import Request

from app.application.aiopen.software_control import request_screen_owner
from app.infrastructure.request_context import (
    get_current_request,
    reset_current_request,
    set_current_request,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    normalize_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


class ApiExecutionError(ValueError):
    pass


def local_api_path(raw: str) -> str:
    """Validate the routing path separately from its query before adding credentials."""
    parts = urlsplit(raw)
    if (
        parts.scheme
        or parts.netloc
        or parts.fragment
        or not raw.startswith("/")
        or raw.startswith("//")
    ):
        raise ApiExecutionError("API 调用只接受本机绝对路径")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ApiExecutionError("API 路径含非法控制字符")
    decoded = parts.path
    for _ in range(4):
        if (
            "\\" in decoded
            or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
            or any(piece in {".", ".."} for piece in decoded.split("/"))
            or decoded.startswith("//")
        ):
            raise ApiExecutionError("API 路径不能包含目录跳转")
        expanded = unquote(decoded, errors="strict")
        if expanded == decoded:
            return decoded
        decoded = expanded
    raise ApiExecutionError("API 路径编码过多")


def _login_request(request: Any) -> tuple[Request, dict[str, str]]:
    from app.application.aiopen.screen_identity import validate_screen_grant
    from app.application.aiopen.service import AIOPEN_STATE
    from app.db import HostSessionLocal
    from app.db.models.user import Session
    from app.infrastructure.auth.dependencies import session_id_from_request

    if request is None:
        raise ApiExecutionError("业务 API 需要已登录账号或账号连接口令")
    key = str(request.headers.get("X-AIOPEN-Key") or "").strip()
    if key:
        grant = AIOPEN_STATE.get("runtime_keys", {}).get(key, {}).get("screen_grant")
        identity = validate_screen_grant(grant)
        if not identity:
            raise ApiExecutionError("连接口令没有有效的账号授权")
        with HostSessionLocal() as db:
            row = db.get(Session, grant["session_record_id"])
            if row is None or sha256(row.session_id.encode()).hexdigest() != grant.get(
                "session_digest"
            ):
                raise ApiExecutionError("连接口令的登录会话已失效")
            sid = row.session_id
    else:
        identity = request_screen_owner(request)
        sid = session_id_from_request(request)
    if not identity or not sid:
        raise ApiExecutionError("业务 API 需要有效的登录会话")
    probe = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/aiopen/invoke",
            "query_string": b"",
            "headers": [(b"x-session-id", sid.encode())],
        }
    )
    if request_screen_owner(probe) != identity:
        raise ApiExecutionError("登录账号或租户已变化")
    return probe, identity


@contextmanager
def authorized_api_request(args: dict[str, Any]) -> Iterator[tuple[dict[str, str], dict[str, str]]]:
    from app.application.agent_orchestrator.task_mod_scope import capture_task_mod_scope

    request = get_current_request()
    if request is None:
        raise ApiExecutionError("业务 API 需要已登录账号或账号连接口令")
    probe, identity = _login_request(request)
    raw_mod = args.get("mod_id", get_request_active_mod_id())
    if not isinstance(raw_mod, str) or (raw_mod and not normalize_active_mod_id(raw_mod)):
        raise ApiExecutionError("mod_id 无效")
    mod_id = normalize_active_mod_id(raw_mod)
    token = set_current_request(probe)
    try:
        if mod_id:
            capture_task_mod_scope(identity["owner_id"], identity["tenant_id"], mod_id=mod_id)
    finally:
        reset_current_request(token)
    headers = {"X-Session-ID": probe.headers["X-Session-ID"], "X-XCAGI-Active-Mod-Id": mod_id}
    # Preserve the caller's tutorial sandbox only for its own login request.
    # A delegated key never inherits a different browser account's cookies.
    if not request.headers.get("X-AIOPEN-Key") and request.cookies.get("xcagi_tutorial_run"):
        from http.cookies import SimpleCookie

        cookie = SimpleCookie()
        cookie["xcagi_tutorial_run"] = request.cookies["xcagi_tutorial_run"]
        headers["Cookie"] = cookie.output(header="").strip()
    mod_token = set_request_active_mod_id(mod_id)
    try:
        # Clear inherited tenant overrides; the actual target middleware resolves
        # the authenticated account (and tutorial sandbox) for each inner request.
        with tenant_scope(None):
            yield headers, {**identity, "mod_id": mod_id}
    finally:
        reset_request_active_mod_id(mod_token)
