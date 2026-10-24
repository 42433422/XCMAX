"""Explicit database selection policies used by startup and legacy repairs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger

from sqlalchemy.engine import Engine

from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class EngineSelection:
    create: Callable[[str], Engine]
    current: Callable[[], Engine]
    logger: Logger

    def _from_url(self, database_url: str | None, warning: str) -> Engine | None:
        url = (database_url or "").strip()
        if url:
            try:
                return self.create(url)
            except RECOVERABLE_ERRORS as exc:
                self.logger.warning("%s: %s", warning, exc)
        return None

    def _current_or_none(self) -> Engine | None:
        try:
            return self.current()
        except RECOVERABLE_ERRORS:
            return None

    def for_auth(self, engine: Engine | None, database_url: str | None) -> Engine | None:
        """A URL takes precedence; an engine proxy must resolve to the current engine."""
        selected = self._from_url(database_url, "auth bootstrap: 无法按 DATABASE_URL 创建引擎")
        if selected is None and engine is not None:
            selected = engine if isinstance(engine, Engine) else self._current_or_none()
        if selected is None:
            selected = self._current_or_none()
        return selected

    def for_columns(
        self, engine: Engine | None, database_url: str | None, *, purpose: str
    ) -> Engine | None:
        """Legacy column repair accepts the caller's engine/proxy as-is after a URL."""
        selected = self._from_url(database_url, f"无法按 DATABASE_URL 创建引擎以补齐 {purpose}")
        if selected is None and engine is not None:
            selected = engine
        if selected is None:
            selected = self._current_or_none()
        return selected

    def prefer_current(self, engine: Engine) -> Engine:
        """Approval, bridge and persona initialization historically prefer the runtime DB."""
        try:
            return self.current()
        except RECOVERABLE_ERRORS:
            return engine

    def required(self, engine: Engine | None, database_url: str | None) -> Engine:
        """IM initialization uses an explicit engine first and propagates resolution errors."""
        if engine is not None:
            return engine
        return self.create(database_url) if database_url else self.current()
