"""Tests for app.fastapi_routes.debug_client_log — coverage ramp C3.3-a.

Covers ``POST /api/debug/client-log`` happy / missing util / exception.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.debug_client_log import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestClientDebugLog:
    def test_success(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.debug_client_log.ingest_client_debug_json",
                return_value={"success": True, "stored": True},
            ),
            patch.dict("sys.modules", {"app.utils.logging_utils": MagicMock()}),
        ):
            r = client.post("/api/debug/client-log", json={"level": "info", "msg": "hi"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True

    def test_import_failure_returns_error(self, client: TestClient) -> None:
        # Force the import inside the handler to fail
        import builtins

        original_import = builtins.__import__

        def fake_import(name: str, *args, **kwargs):
            if "logging_utils" in name and "utils" in name:
                raise ImportError("forced")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            r = client.post("/api/debug/client-log", json={"level": "error", "msg": "boom"})
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_empty_body_uses_default(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.debug_client_log.ingest_client_debug_json",
            return_value={"success": True},
        ):
            r = client.post("/api/debug/client-log", json={})
        assert r.status_code == 200
