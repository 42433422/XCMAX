"""Local market-token cache with an explicit SQL session repository."""

from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from logging import Logger
from typing import TYPE_CHECKING, Literal, Protocol

from sqlalchemy.orm import Session

from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.db.models.user import Session as UserSession

TokenKind = Literal["access", "refresh"]


class SessionTokenRepository(Protocol):
    def save(self, sid: str, access: str, refresh: str) -> None: ...
    def clear(self, sid: str) -> None: ...
    def read(self, sid: str, kind: TokenKind) -> str: ...
    def latest(self, kind: TokenKind, user_id: int | None = None) -> str: ...
    def owner(self, sid: str) -> int | None: ...


@dataclass
class SQLSessionTokens:
    database: Callable[[], AbstractContextManager[Session]]
    session_model: Callable[[], type["UserSession"]]

    def save(self, sid: str, access: str, refresh: str) -> None:
        model = self.session_model()
        with self.database() as db:
            row = db.query(model).filter(model.session_id == sid).first()
            if row is not None:
                row.market_access_token = access
                if refresh:
                    row.market_refresh_token = refresh
                db.commit()

    def clear(self, sid: str) -> None:
        model = self.session_model()
        with self.database() as db:
            row = db.query(model).filter(model.session_id == sid).first()
            if row is not None:
                if getattr(row, "market_access_token", None):
                    row.market_access_token = None
                if getattr(row, "market_refresh_token", None):
                    row.market_refresh_token = None
                db.commit()

    def read(self, sid: str, kind: TokenKind) -> str:
        model = self.session_model()
        with self.database() as db:
            row = db.query(model).filter(model.session_id == sid).first()
            raw = getattr(row, f"market_{kind}_token", None) if row is not None else None
            return (raw or "").strip() if raw is not None else ""

    def latest(self, kind: TokenKind, user_id: int | None = None) -> str:
        model = self.session_model()
        with self.database() as db:
            column = model.market_access_token if kind == "access" else model.market_refresh_token
            query = db.query(model).filter(column.isnot(None))
            if user_id is not None:
                query = query.filter(model.user_id == user_id)
            for row in query.order_by(model.created_at.desc()).limit(10).all():
                token = str(getattr(row, f"market_{kind}_token", "") or "").strip()
                if token:
                    return token
        return ""

    def owner(self, sid: str) -> int | None:
        model = self.session_model()
        with self.database() as db:
            row = db.query(model).filter(model.session_id == sid).first()
            return getattr(row, "user_id", None) if row is not None else None


@dataclass
class SessionTokens:
    access_tokens: MutableMapping[str, str]
    refresh_tokens: MutableMapping[str, str]
    repository: SessionTokenRepository
    logger: Logger

    def save(self, session_id: str, token: str, refresh_token: str | None = None) -> None:
        sid, access = (session_id or "").strip(), (token or "").strip()
        if not sid or not access:
            return
        self.access_tokens[sid] = access
        refresh = (refresh_token or "").strip()
        if refresh:
            self.refresh_tokens[sid] = refresh
        try:
            self.repository.save(sid, access, refresh)
        except RECOVERABLE_ERRORS:
            self.logger.exception(
                "save_session_market_token: failed to persist market token for session_id=%s", sid
            )

    def clear(self, session_id: str) -> None:
        sid = (session_id or "").strip()
        if sid:
            self.access_tokens.pop(sid, None)
            self.refresh_tokens.pop(sid, None)
        try:
            self.repository.clear(sid)
        except RECOVERABLE_ERRORS:
            self.logger.exception(
                "clear_session_market_token: failed to clear persisted token for session_id=%s", sid
            )

    def read(self, session_id: str, kind: TokenKind) -> str:
        sid = (session_id or "").strip()
        if not sid:
            return ""
        cache = self.access_tokens if kind == "access" else self.refresh_tokens
        cached = cache.get(sid, "").strip()
        if cached:
            return cached
        operation = "session_market_token" if kind == "access" else "session_market_refresh_token"
        try:
            token = self.repository.read(sid, kind)
            if token:
                cache[sid] = token
                return token
        except RECOVERABLE_ERRORS:
            self.logger.exception("%s: DB read failed for session_id=%s", operation, sid)
        return ""

    def latest(self, kind: TokenKind, user_id: int | None = None) -> str:
        operation = (
            "latest_session_market_token"
            if kind == "access"
            else "latest_session_market_refresh_token"
        )
        try:
            return self.repository.latest(kind, user_id)
        except RECOVERABLE_ERRORS:
            self.logger.exception("%s: DB read failed", operation)
            return ""

    def owner(self, session_id: str) -> int | None:
        sid = (session_id or "").strip()
        if not sid:
            return None
        try:
            return self.repository.owner(sid)
        except RECOVERABLE_ERRORS:
            self.logger.exception("_user_id_from_session: DB read failed for sid=%s", sid[:8])
            return None
