"""Platform shell upload routes require session (Wave 0)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

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
