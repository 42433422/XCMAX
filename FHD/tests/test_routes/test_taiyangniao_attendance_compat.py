from __future__ import annotations

from io import BytesIO

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.fastapi_routes.taiyangniao_attendance_compat import (
    DEFAULT_TEMPLATE_RELPATH,
    router,
)


def test_attendance_rules_host_route() -> None:
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/api/mod/taiyangniao-pro/attendance/rules")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["config"]["default_template_relpath"] == DEFAULT_TEMPLATE_RELPATH
    assert body["data"]["schedule_groups"]


def test_attendance_download_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "424").mkdir()
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get(
            "/api/mod/taiyangniao-pro/attendance/download",
            params={"relpath": "424/does-not-exist.xlsx"},
        )

    assert response.status_code == 404
    assert response.json()["success"] is False


def test_attendance_convert_upload_rejects_bad_extension() -> None:
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/api/mod/taiyangniao-pro/attendance/convert-upload",
            files={"file": ("notes.txt", BytesIO(b"hello"), "text/plain")},
        )

    assert response.status_code == 400
    assert "unsupported" in response.json()["error"]


def test_attendance_convert_upload_rejects_wrong_template(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/api/mod/taiyangniao-pro/attendance/convert-upload",
            data={"template_relpath": "wrong/template.xlsx"},
            files={
                "file": (
                    "attendance.xlsx",
                    BytesIO(b"PK\x03\x04"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert response.status_code == 400
    assert "固定模板" in response.json()["error"]
