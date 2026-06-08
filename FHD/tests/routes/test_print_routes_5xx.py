"""Tests for app.fastapi_routes.print_routes — coverage ramp C3.3-a.

Covers the helper functions and a few key endpoints:
* ``_create_print_confirm_token`` + ``_consume_print_confirm_token``.
* ``_cleanup_print_confirm_cache`` removes expired entries.
* ``GET /api/print/printers`` delegates to service.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import print_routes
from app.fastapi_routes.print_routes import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestConfirmTokenCache:
    def test_create_and_consume(self) -> None:
        print_routes._print_confirm_cache.clear()
        token = print_routes._create_print_confirm_token({"job_id": "J1"})
        assert token in print_routes._print_confirm_cache
        payload = print_routes._consume_print_confirm_token(token)
        assert payload["job_id"] == "J1"
        assert token not in print_routes._print_confirm_cache

    def test_consume_unknown_returns_empty(self) -> None:
        print_routes._print_confirm_cache.clear()
        assert print_routes._consume_print_confirm_token("nope") == {}

    def test_cleanup_removes_expired(self) -> None:
        print_routes._print_confirm_cache.clear()
        print_routes._print_confirm_cache["old"] = {
            "expires_at": time.time() - 100,
            "job_id": "J1",
        }
        print_routes._print_confirm_cache["fresh"] = {
            "expires_at": time.time() + 100,
            "job_id": "J2",
        }
        print_routes._cleanup_print_confirm_cache()
        assert "old" not in print_routes._print_confirm_cache
        assert "fresh" in print_routes._print_confirm_cache


class TestPrintersEndpoint:
    def test_success(self, client: TestClient) -> None:
        with patch("app.fastapi_routes.print_routes._svc") as svc:
            svc.return_value.get_printers.return_value = {
                "success": True,
                "data": [{"id": "P1", "name": "HP"}],
            }
            r = client.get("/api/print/printers")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["data"][0]["id"] == "P1"
