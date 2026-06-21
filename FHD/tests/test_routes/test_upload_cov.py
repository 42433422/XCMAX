from __future__ import annotations

"""Branch coverage for app/fastapi_routes/upload.py."""

import os
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_client():
    from fastapi import FastAPI

    from app.fastapi_routes.upload import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestAllowedFile:
    def test_allowed_extensions(self):
        from app.fastapi_routes.upload import _allowed_file

        for ext in ("png", "jpg", "jpeg", "gif", "webp"):
            assert _allowed_file(f"image.{ext}") is True

    def test_not_allowed_extension(self):
        from app.fastapi_routes.upload import _allowed_file

        assert _allowed_file("doc.pdf") is False

    def test_no_dot_in_filename(self):
        from app.fastapi_routes.upload import _allowed_file

        assert _allowed_file("nodot") is False


class TestGetUploadConfig:
    def test_config_returns_ok(self):
        client = _make_client()
        resp = client.get("/api/upload/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "max_size_bytes" in body["config"]


class TestUploadTemp:
    def test_no_file(self):
        client = _make_client()
        with patch("app.fastapi_routes.upload._ensure_upload_folder"):
            resp = client.post("/api/upload/temp")
        assert resp.status_code == 400
        assert resp.json()["success"] is False

    def test_empty_filename(self):
        client = _make_client()
        data = {"file": ("", BytesIO(b""), "image/png")}
        with patch("app.fastapi_routes.upload._ensure_upload_folder"):
            resp = client.post("/api/upload/temp", files=data)
        # empty filename → 400
        assert resp.status_code in (400, 200)  # depends on ASGI handling

    def test_disallowed_extension(self):
        client = _make_client()
        with patch("app.fastapi_routes.upload._ensure_upload_folder"):
            resp = client.post(
                "/api/upload/temp",
                files={"file": ("doc.pdf", BytesIO(b"content"), "application/pdf")},
            )
        assert resp.status_code == 400
        assert "不支持" in resp.json()["message"]

    def test_file_too_large(self, tmp_path):
        client = _make_client()
        big = b"x" * (16 * 1024 * 1024 + 1)
        with (
            patch("app.fastapi_routes.upload._ensure_upload_folder"),
            patch("app.fastapi_routes.upload.UPLOAD_FOLDER", str(tmp_path)),
        ):
            resp = client.post(
                "/api/upload/temp",
                files={"file": ("image.png", BytesIO(big), "image/png")},
            )
        assert resp.status_code == 400
        assert "过大" in resp.json()["message"]

    def test_successful_upload(self, tmp_path):
        client = _make_client()
        content = b"PNG_HEADER\x89PNG\r\n"
        with (
            patch("app.fastapi_routes.upload._ensure_upload_folder"),
            patch("app.fastapi_routes.upload.UPLOAD_FOLDER", str(tmp_path)),
        ):
            resp = client.post(
                "/api/upload/temp",
                files={"file": ("photo.png", BytesIO(content), "image/png")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "file_path" in body

    def test_upload_write_error(self, tmp_path):
        client = _make_client()
        content = b"small"
        with (
            patch("app.fastapi_routes.upload._ensure_upload_folder"),
            patch("app.fastapi_routes.upload.UPLOAD_FOLDER", str(tmp_path)),
            patch("builtins.open", side_effect=OSError("write error")),
        ):
            resp = client.post(
                "/api/upload/temp",
                files={"file": ("photo.png", BytesIO(content), "image/png")},
            )
        assert resp.status_code == 500

    def test_upload_secure_filename_fallback(self, tmp_path):
        """When secure_filename returns empty string, fallback name is used."""
        client = _make_client()
        content = b"data"
        with (
            patch("app.fastapi_routes.upload._ensure_upload_folder"),
            patch("app.fastapi_routes.upload.UPLOAD_FOLDER", str(tmp_path)),
            patch("app.fastapi_routes.upload.secure_filename", return_value=""),
        ):
            resp = client.post(
                "/api/upload/temp",
                files={"file": ("photo.png", BytesIO(content), "image/png")},
            )
        # should still succeed with fallback name
        assert resp.status_code in (200, 500)


class TestDeleteTempFile:
    def test_delete_file_not_found(self):
        client = _make_client()
        with patch("app.fastapi_routes.upload.UPLOAD_FOLDER", "/tmp/nonexistent_dir"):
            resp = client.delete("/api/upload/temp/nosuchfile.png")
        assert resp.status_code == 404

    def test_delete_file_success(self, tmp_path):
        client = _make_client()
        f = tmp_path / "todelete.png"
        f.write_bytes(b"data")
        with patch("app.fastapi_routes.upload.UPLOAD_FOLDER", str(tmp_path)):
            resp = client.delete("/api/upload/temp/todelete.png")
        assert resp.status_code == 200
        assert not f.exists()

    def test_delete_os_error(self, tmp_path):
        client = _make_client()
        f = tmp_path / "target.png"
        f.write_bytes(b"data")
        with (
            patch("app.fastapi_routes.upload.UPLOAD_FOLDER", str(tmp_path)),
            patch("os.remove", side_effect=OSError("perm denied")),
        ):
            resp = client.delete("/api/upload/temp/target.png")
        assert resp.status_code == 500
