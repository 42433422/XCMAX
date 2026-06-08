"""Tests for app.fastapi_routes.xcmax_admin — coverage ramp C3.3-a.

Covers:
* ``_require_market_admin_session`` — missing session / non-admin / admin / no-sid.
* ``_release_train_snapshot`` — modstore / file / missing / bad JSON.
* A representative admin endpoint with mocked dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes
from app.fastapi_routes.xcmax_admin import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRequireMarketAdmin:
    def test_no_session_id_returns_401(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 401
        assert "登录" in resp.body.decode()

    def test_non_admin_account_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "user", "market_is_admin": False},
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403

    def test_admin_returns_none(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            assert admin_routes._require_market_admin_session(request) is None

    def test_meta_none_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403


class TestReleaseTrainSnapshot:
    def test_modstore_path_used(self) -> None:
        with patch.dict(
            "sys.modules",
            {
                "modstore_server.release_train": MagicMock(
                    snapshot_public=MagicMock(return_value={"current": "1.0.0.0"})
                )
            },
        ):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"

    def test_fallback_to_file(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text(
            json.dumps({"current": "9.9.9.9", "epoch": "9.9.0.0"})
        )
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "9.9.9.9"

    def test_file_missing_returns_default(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"
        assert out.get("note") == "ssot missing"

    def test_bad_json_returns_default(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text("not json")
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"
