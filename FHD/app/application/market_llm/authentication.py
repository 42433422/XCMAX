"""Resolve explicitly configured or account-scoped market credentials."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import Protocol, cast

from fastapi import Request

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import Connection


class LatestToken(Protocol):
    def __call__(self, user_id: int | None = None) -> str: ...


@dataclass(frozen=True)
class SessionPorts:
    session_id: Callable[[Request], str]
    token: Callable[[str], str]
    owner: Callable[[str], int | None]
    latest: LatestToken


@dataclass(frozen=True)
class Credential:
    token: str
    source: str


def load_session_ports() -> SessionPorts:
    from app.fastapi_routes.market_account import (
        _user_id_from_session,
        latest_session_market_token,
        session_id_from_request,
        session_market_token,
    )

    return SessionPorts(
        session_id_from_request,
        session_market_token,
        _user_id_from_session,
        latest_session_market_token,
    )


def _strip_bearer_prefix(value: str) -> str:
    token = (value or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def resolve_credential(
    explicit: str,
    environment: str,
    session_id: str | None,
    request: object,
    load: Callable[[], SessionPorts],
    logger: Logger,
) -> Credential:
    if explicit:
        return Credential(explicit, "kwargs")
    # Session-bound calls must not silently inherit a process-wide env token
    # (#2619 request-model isolation).
    if environment and not (session_id or request):
        return Credential(environment, "env")
    if not session_id and not request:
        return Credential(environment or "", "env")
    try:
        ports = load()
        sid = session_id or (ports.session_id(cast(Request, request)) if request else "")
        if not sid:
            return Credential("", "env")
        token = ports.token(sid)
        if token:
            return Credential(token, "session")
        # An unresolved session must never turn into the repository's global
        # latest-token query. Only a known owner can borrow their own token.
        owner = ports.owner(sid)
        if owner is not None:
            token = ports.latest(user_id=owner)
            if token:
                return Credential(token, "session")
    except ImportError as exc:
        logger.error("无法导入market_account模块: %s", exc)
    except RECOVERABLE_ERRORS as exc:
        logger.error("从Session获取Token失败: %s", exc, exc_info=True)
    return Credential("", "env")


def refresh_credential(
    session_id: str | None,
    request: object,
    load: Callable[[], SessionPorts],
    logger: Logger,
) -> str:
    try:
        ports = load()
        sid = session_id or (ports.session_id(cast(Request, request)) if request else "")
        if not sid:
            logger.warning("refresh_token_from_session: 无有效Session ID")
            return ""
        return _strip_bearer_prefix(ports.token(sid))
    except RECOVERABLE_ERRORS as exc:
        logger.error("刷新Token失败: %s", exc, exc_info=True)
        return ""


def validate_demo_destination(connection: Connection) -> None:
    try:
        from app.application.surface_audit_demo_account import is_local_demo_market_token
        from app.fastapi_routes.market_account import _is_local_market_base
    except ImportError:
        return
    if is_local_demo_market_token(connection.auth_token) and not _is_local_market_base(
        connection.platform_url
    ):
        raise ValueError(
            "当前会话为本地演示令牌，无法调用官网 LLM。请设置 XCAGI_USE_REMOTE_MARKET=1 重启后端并重新登录。"
        )
