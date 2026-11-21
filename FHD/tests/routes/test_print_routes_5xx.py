"""Printer read projection; write admission is covered by business capability routes."""

from __future__ import annotations

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
    with TestClient(app) as test_client:
        yield test_client


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
