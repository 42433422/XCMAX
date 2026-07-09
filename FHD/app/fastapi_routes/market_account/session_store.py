"""Market session token storage."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request

import app.fastapi_routes.market_account._patch as _p

logger = logging.getLogger(__name__)
_MARKET_SESSION_TOKENS: dict[str, str] = {}
_MARKET_SESSION_REFRESH_TOKENS: dict[str, str] = {}

def session_id_from_request(request: Request) -> str:
    """与 auth dependencies 一致：按客户端壳读 admin_session_id / session_id。"""
    from app.infrastructure.auth.dependencies import session_id_from_request as _sid

    return _sid(request)
def bind_market_auth_to_session(
    request: Request,
    market_result: dict[str, Any],
) -> tuple[str, str]:
    """Write market JWT from ``login_market_with_password`` (or register) onto the current FHD session."""
    token = str(market_result.get("token") or "").strip()
    refresh = str(market_result.get("refresh_token") or "").strip()
    if token:
        _p.save_session_market_token(_p.session_id_from_request(request), token, refresh or None)
    return token, refresh
def save_session_market_token(
    session_id: str,
    token: str,
    refresh_token: str | None = None,
) -> None:
    sid = (session_id or "").strip()
    tok = (token or "").strip()
    if not sid or not tok:
        return
    _MARKET_SESSION_TOKENS[sid] = tok
    rtok = (refresh_token or "").strip()
    if rtok:
        _MARKET_SESSION_REFRESH_TOKENS[sid] = rtok
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is not None:
                row.market_access_token = tok
                if rtok:
                    row.market_refresh_token = rtok
                db.commit()
    except _p.RECOVERABLE_ERRORS:
        logger.exception(
            "save_session_market_token: failed to persist market token for session_id=%s", sid
        )
def clear_session_market_token(session_id: str) -> None:
    sid = (session_id or "").strip()
    if sid:
        _MARKET_SESSION_TOKENS.pop(sid, None)
        _MARKET_SESSION_REFRESH_TOKENS.pop(sid, None)
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            if row is not None:
                if getattr(row, "market_access_token", None):
                    row.market_access_token = None
                if getattr(row, "market_refresh_token", None):
                    row.market_refresh_token = None
                db.commit()
    except _p.RECOVERABLE_ERRORS:
        logger.exception(
            "clear_session_market_token: failed to clear persisted token for session_id=%s", sid
        )
def session_market_token(session_id: str) -> str:
    sid = (session_id or "").strip()
    if not sid:
        return ""
    mem = _MARKET_SESSION_TOKENS.get(sid, "").strip()
    if mem:
        return mem
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            raw = getattr(row, "market_access_token", None) if row is not None else None
            t = (raw or "").strip() if raw is not None else ""
            if t:
                _MARKET_SESSION_TOKENS[sid] = t
                return t
    except _p.RECOVERABLE_ERRORS:
        logger.exception("session_market_token: DB read failed for session_id=%s", sid)
    return ""
def session_market_refresh_token(session_id: str) -> str:
    sid = (session_id or "").strip()
    if not sid:
        return ""
    mem = _MARKET_SESSION_REFRESH_TOKENS.get(sid, "").strip()
    if mem:
        return mem
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            raw = getattr(row, "market_refresh_token", None) if row is not None else None
            t = (raw or "").strip() if raw is not None else ""
            if t:
                _MARKET_SESSION_REFRESH_TOKENS[sid] = t
                return t
    except _p.RECOVERABLE_ERRORS:
        logger.exception("session_market_refresh_token: DB read failed for session_id=%s", sid)
    return ""
def latest_session_market_refresh_token() -> str:
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            rows = (
                db.query(UserSession)
                .filter(UserSession.market_refresh_token.isnot(None))
                .order_by(UserSession.created_at.desc())
                .limit(10)
                .all()
            )
            for row in rows:
                tok = str(getattr(row, "market_refresh_token", "") or "").strip()
                if tok:
                    return tok
    except _p.RECOVERABLE_ERRORS:
        logger.exception("latest_session_market_refresh_token: DB read failed")
    return ""
def latest_session_market_token(user_id: int | None = None) -> str:
    """Desktop fallback: use the newest persisted market token when browser cookies are unavailable.

    LAN/IP access can miss the ``session_id`` cookie even though the local single-user desktop
    session has a freshly persisted market token from login. Prefer that over stale localStorage
    tokens sent by the SPA.

    多用户环境必须传 ``user_id`` 以避免串号：若不传则返回全局最新 token（仅适用于
    单用户桌面模式）。云后端/多用户场景下，调用方应传入当前登录用户的 ``user_id``，
    本函数将只返回该用户绑定的市场 token，防止 A 用户拿到 B 用户的市场凭证。
    """
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            query = db.query(UserSession).filter(UserSession.market_access_token.isnot(None))
            if user_id is not None:
                query = query.filter(UserSession.user_id == user_id)
            rows = query.order_by(UserSession.created_at.desc()).limit(10).all()
            for row in rows:
                tok = str(getattr(row, "market_access_token", "") or "").strip()
                if tok:
                    return tok
    except _p.RECOVERABLE_ERRORS:
        logger.exception("latest_session_market_token: DB read failed")
    return ""
def _user_id_from_session(session_id: str) -> int | None:
    """从 session_id 反查 user_id，用于多用户环境下的 market token fallback 隔离。

    返回 None 表示查不到（如 session 不存在或 DB 不可用），调用方应保持原 fallback 行为。
    """
    sid = (session_id or "").strip()
    if not sid:
        return None
    try:
        from app.db.models.user import Session as UserSession
        from app.db.session import get_db

        with get_db() as db:
            row = db.query(UserSession).filter(UserSession.session_id == sid).first()
            return getattr(row, "user_id", None) if row is not None else None
    except _p.RECOVERABLE_ERRORS:
        logger.exception("_user_id_from_session: DB read failed for sid=%s", sid[:8])
        return None
