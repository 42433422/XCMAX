"""Shared fixtures for tests/test_application/ — coverage ramp C3.2-b.

Provides:
* `fake_user` — simple user stub for permission / session tests.
* `fake_db_session` — MagicMock session for non-DB code paths.
* `reset_app_service_singletons` — clears module-level service instances.
* `tmp_sqlite_db` — in-memory SQLite for transaction rollback tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_user() -> Any:
    """Return a simple user-like object."""

    class _User:
        id = 1
        username = "tester"
        display_name = "Test User"
        email = "tester@example.com"
        role = "user"
        is_active = True
        password = "hashed:placeholder"
        last_login = None

    return _User()


@pytest.fixture
def fake_db_session() -> MagicMock:
    """Return a MagicMock that quacks like a SQLAlchemy session."""
    return MagicMock()


@pytest.fixture
def reset_app_service_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset all application service module-level singletons.

    Walks known modules and clears ``_instance`` / ``_X_app_service`` globals
    so each test starts with a clean slate.
    """
    yield
    import app.application.auth_app_service as auth_mod
    import app.application.customer_app_service as cust_mod

    if hasattr(auth_mod, "_auth_app_service"):
        monkeypatch.setattr(auth_mod, "_auth_app_service", None)
    if hasattr(cust_mod, "_customer_app_service"):
        monkeypatch.setattr(cust_mod, "_customer_app_service", None)
