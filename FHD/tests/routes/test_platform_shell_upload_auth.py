"""Platform shell upload routes require session (Wave 0)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(*, authenticated: bool) -> TestClient:
    from app.fastapi_routes.platform_shell_routes import router

    app = FastAPI()
    app.include_router(router)
    if authenticated:

        def _fake_user(request):
            return MagicMock(id=1, is_active=True, tenant_id=1)

        with patch(
            "app.infrastructure.auth.dependencies.resolve_session_user",
            side_effect=_fake_user,
        ):
            pass
    return TestClient(app, raise_server_exceptions=False)


class TestPlatformShellUploadAuth:
    def test_office_sample_upload_401_without_session(self):
        from app.fastapi_routes.platform_shell_routes import router

        app = FastAPI()
        app.include_router(router)
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
        ):
            resp = client.post(
                "/api/platform-shell/office-sample-upload",
                files={"file": ("sample.xlsx", BytesIO(b"x"), "application/octet-stream")},
            )
        assert resp.status_code == 401

    def test_chat_office_upload_401_without_session(self):
        from app.fastapi_routes.platform_shell_routes import router

        app = FastAPI()
        app.include_router(router)
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
        ):
            resp = client.post(
                "/api/platform-shell/chat-office-file-upload",
                files={"file": ("chat.xlsx", BytesIO(b"x"), "application/octet-stream")},
            )
        assert resp.status_code == 401
        assert "请先登录" in resp.text

    def test_route_messages_are_readable_text(self):
        from pathlib import Path

        import app.fastapi_routes.platform_shell_routes as routes
        import app.mod_sdk.deliverable_status as status

        for module in (routes, status):
            assert "????" not in Path(module.__file__).read_text(encoding="utf-8")

    def test_office_sample_upload_ok_with_session(self):
        from app.fastapi_routes.platform_shell_routes import router

        app = FastAPI()
        app.include_router(router)
        user = MagicMock(id=1, is_active=True)
        with (
            TestClient(app, raise_server_exceptions=False) as client,
            patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
            patch(
                "app.fastapi_routes.platform_shell_routes._save_workspace_upload",
                return_value={"file_path": "uploads/tutorial/x.xlsx"},
            ),
        ):
            resp = client.post(
                "/api/platform-shell/office-sample-upload",
                files={"file": ("sample.xlsx", BytesIO(b"x"), "application/octet-stream")},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


@pytest.mark.parametrize("suffix", ["xlsx", "xls"])
def test_chat_upload_binds_original_bytes_to_authenticated_owner(tmp_path, monkeypatch, suffix):
    from types import SimpleNamespace

    from app.fastapi_routes.platform_shell_routes import router

    user = SimpleNamespace(id=7, tenant_id=9)
    registration = MagicMock(return_value={"upload_id": "owned-upload"})
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr("app.application.elt.service_uploads.register_chat_upload", registration)
    app = FastAPI()
    app.include_router(router)
    with patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user):
        response = TestClient(app).post(
            "/api/platform-shell/chat-office-file-upload",
            files={"file": (f"report.{suffix}", b"original", "application/octet-stream")},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    if suffix == "xls":
        assert "upload_id" not in data and "另存为 .xlsx" in data["attachment_warning"]
        registration.assert_not_called()
        return
    assert data["upload_id"] == "owned-upload"
    args = registration.call_args.args
    assert args[:3] == (user, "report.xlsx", "application/octet-stream")
    assert args[3].getvalue() == b"original"
