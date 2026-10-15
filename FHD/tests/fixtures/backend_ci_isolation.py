"""Explicit test-owned database and bounded upstream throttling handling."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError

import pytest


@pytest.fixture
def isolated_login_host_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as host_db
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'login.sqlite'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(host_db, "HostSessionLocal", sessionmaker(bind=engine))
    try:
        yield engine
    finally:
        engine.dispose()


def retry_throttled_fetch(fetch, *, sleep=time.sleep):
    """Retry only 429, honor Retry-After, and still fail when retries exhaust."""

    def wrapped(path):
        for attempt in range(3):
            try:
                return fetch(path)
            except HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                raw = exc.headers.get("Retry-After", "") if exc.headers else ""
                try:
                    delay = float(raw)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
                    except (TypeError, ValueError):
                        delay = 15 * (attempt + 1)
                if delay > 120:
                    raise
                sleep(max(0, delay))
        raise AssertionError("Unreachable retry state")

    return wrapped
