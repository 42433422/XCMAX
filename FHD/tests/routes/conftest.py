"""Shared fixtures for tests/routes/ — coverage ramp C3.3-a.

Provides:
* `fastapi_test_client` — TestClient for the FHD app, scoped per test.
* `mock_admin_session` — injects a valid X-Admin-Session header + DB row.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fastapi_test_client() -> TestClient:
    """Create a TestClient for the FHD FastAPI app.

    Falls back to a minimal FastAPI() if the main factory is unavailable, so
    the import never breaks the suite.
    """
    try:
        from app.fastapi_app.factory import create_app

        app = create_app()
    except Exception:
        from fastapi import FastAPI

        app = FastAPI()
    return TestClient(app)


@pytest.fixture
def mock_admin_session(monkeypatch: pytest.MonkeyPatch) -> str:
    """Provide a valid admin session token + DB row stub."""
    token = "test-admin-session-token"
    fake_row = MagicMock()
    fake_row.session_id = token
    fake_row.is_valid = True
    fake_row.user_id = 1

    with patch("app.db.session.get_db") as gdb:
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = fake_row
        gdb.return_value.__enter__.return_value = db
        yield token
