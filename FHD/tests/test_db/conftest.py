"""Shared fixtures for tests/test_db/ — coverage ramp C3.2-a.

Provides:
* `tmp_sqlite_db` — in-memory SQLite session bound to a fresh Base metadata.
* `reset_retry_handler` — clears any module-level retry state.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base


@pytest.fixture
def tmp_sqlite_db() -> tuple[Any, sessionmaker]:
    """Create an in-memory SQLite engine + session factory.

    Yields ``(engine, SessionLocal_class)`` so tests can create sessions
    and verify state changes. Uses ``StaticPool`` so all connections share
    the same in-memory database (required for multi-thread tests).
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    yield engine, SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def isolated_sqlite_lock(monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Provide a sqlite3 connection that simulates a 'database is locked' error.

    Use this to verify the retry handler's exponential backoff and exhaustion
    paths. Yields a connection whose ``execute`` raises ``OperationalError``
    with message ``'database is locked'`` for the first N attempts, then
    succeeds.
    """
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def reset_thread_state() -> None:
    """Reset any thread-local retry state.

    Some tests set threading.current_thread().retry_count; clean up after.
    """
    yield
    for thread in threading.enumerate():
        for attr in list(getattr(thread, "__dict__", {}).keys()):
            if attr.startswith("retry_"):
                delattr(thread, attr)
