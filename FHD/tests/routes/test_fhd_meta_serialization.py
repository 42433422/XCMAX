"""Tests for app.fastapi_routes.fhd_meta — coverage ramp C3.3-a.

Covers ``/api/fhd/db-tokens/status`` with various states of the
read/write DB tokens, with/without active_mod_id.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.fhd_meta import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestDbTokensStatus:
    def test_both_tokens_configured(self, client: TestClient) -> None:
        with (
            patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=""),
            patch(
                "app.infrastructure.auth.db_token.configured_db_read_token", return_value="RTOKEN"
            ),
            patch(
                "app.infrastructure.auth.db_token.configured_db_write_token", return_value="WTOKEN"
            ),
        ):
            r = client.get("/api/fhd/db-tokens/status")
        assert r.status_code == 200
        data = r.json()
        assert data["read_token_configured"] is True
        assert data["write_token_configured"] is True
        assert data["active_mod_id"] == ""

    def test_no_tokens(self, client: TestClient) -> None:
        with (
            patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=None),
            patch("app.infrastructure.auth.db_token.configured_db_read_token", return_value=""),
            patch("app.infrastructure.auth.db_token.configured_db_write_token", return_value=""),
        ):
            r = client.get("/api/fhd/db-tokens/status")
        assert r.json()["read_token_configured"] is False

    def test_with_active_mod_id(self, client: TestClient) -> None:
        with (
            patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value="mod-x"),
            patch("app.infrastructure.auth.db_token.configured_db_read_token", return_value="R"),
            patch("app.infrastructure.auth.db_token.configured_db_write_token", return_value=None),
        ):
            r = client.get("/api/fhd/db-tokens/status")
        data = r.json()
        assert data["active_mod_id"] == "mod-x"
        assert data["read_token_configured"] is True
        assert data["write_token_configured"] is False

    def test_get_request_mod_id_failure_falls_back(self, client: TestClient) -> None:
        with (
            patch(
                "app.request_active_mod_ctx.get_request_active_mod_id",
                side_effect=RuntimeError("ctx missing"),
            ),
            patch("app.infrastructure.auth.db_token.configured_db_read_token", return_value=""),
            patch("app.infrastructure.auth.db_token.configured_db_write_token", return_value=""),
        ):
            r = client.get("/api/fhd/db-tokens/status")
        assert r.status_code == 200
        assert r.json()["active_mod_id"] == ""
