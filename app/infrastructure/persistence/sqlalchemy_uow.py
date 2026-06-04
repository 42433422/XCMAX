"""SQLAlchemy Unit of Work — single session boundary with commit/rollback."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SqlAlchemyUnitOfWork:
    """
    Usage::

        with SqlAlchemyUnitOfWork() as session:
            session.add(...)
        # commits on success, rolls back on exception
    """

    def __init__(
        self,
        session_factory: Callable[[], Any] | None = None,
        on_commit: Callable[[], None] | None = None,
    ):
        self._session_factory = session_factory
        self._on_commit = on_commit
        self._session: Any = None

    def __enter__(self) -> Any:
        if self._session_factory is not None:
            self._session = self._session_factory()
        else:
            from app.db import SessionLocal

            self._session = SessionLocal()
        return self._session

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._session is None:
            return
        try:
            if exc_type is None:
                self._session.commit()
                if self._on_commit is not None:
                    try:
                        self._on_commit()
                    except Exception:
                        logger.exception("SqlAlchemyUnitOfWork on_commit hook failed")
            else:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None


@contextmanager
def sqlalchemy_uow_session(
    *,
    session_factory: Callable[[], Any] | None = None,
    on_commit: Callable[[], None] | None = None,
) -> Iterator[Any]:
    """Context-manager equivalent of ``SqlAlchemyUnitOfWork``."""
    uow = SqlAlchemyUnitOfWork(session_factory=session_factory, on_commit=on_commit)
    with uow as session:
        yield session
