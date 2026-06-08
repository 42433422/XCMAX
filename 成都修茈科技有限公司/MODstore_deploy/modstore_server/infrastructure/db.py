"""Database session infrastructure."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from modstore_server.models import get_session_factory


def get_db() -> Iterator[Session]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
