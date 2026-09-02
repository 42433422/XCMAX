"""COVERAGE_RAMP Phase 56: fastapi_routes/domains static & misc (mocked TestClient)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def static_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes.domains.static import routes as static_routes

    vue_dist = tmp_path / "templates" / "vue-dist"
    vue_dist.mkdir(parents=True)
    (vue_dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (vue_dist / "vite.svg").write_text("<svg/>", encoding="utf-8")
    static_dir = vue_dist / "static"
    static_dir.mkdir()
    (static_dir / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setattr(static_routes, "get_base_dir", lambda: str(tmp_path))
    app = FastAPI()
    app.include_router(static_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_static_index_serves_vue(static_client: TestClient) -> None:
    r = static_client.get("/")
    assert r.status_code == 200
    assert "ok" in r.text


def test_static_asset_and_vite_svg(static_client: TestClient) -> None:
    r = static_client.get("/static/app.js")
    assert r.status_code == 200
    r2 = static_client.get("/vite.svg")
    assert r2.status_code == 200


def test_static_missing_asset_404(static_client: TestClient) -> None:
    r = static_client.get("/static/missing.js")
    assert r.status_code == 404


def test_static_index_fallback_404(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fastapi_routes.domains.static import routes as static_routes

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(static_routes, "get_base_dir", lambda: str(empty))
    app = FastAPI()
    app.include_router(static_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/")
    assert r.status_code == 404
    assert r.json()["success"] is False


def test_misc_require_login_unauthenticated() -> None:
    from app.fastapi_routes.domains.misc import helpers as misc_helpers

    req = MagicMock()
    with patch(
        "app.fastapi_routes.domains.misc.helpers.resolve_session_user",
        return_value=None,
    ):
        with patch(
            "app.fastapi_routes.domains.misc.helpers.get_logged_in_user",
            side_effect=__import__("fastapi").HTTPException(status_code=401, detail="未登录"),
        ):
            user, err = misc_helpers._require_login_user(req)
    assert user is None
    assert err is not None
    assert err.status_code == 401


def test_misc_require_permission_forbidden() -> None:
    from app.fastapi_routes.domains.misc import helpers as misc_helpers

    req = MagicMock()
    auth = MagicMock()
    auth.has_permission.return_value = False
    with (
        patch.object(misc_helpers, "_require_login_user", return_value=({"id": 1}, None)),
        patch("app.application.facades.session_facade.get_auth_service", return_value=auth),
    ):
        user, err = misc_helpers._require_permission(req, "admin.write")
    assert user is None
    assert err is not None
    assert err.status_code == 403
