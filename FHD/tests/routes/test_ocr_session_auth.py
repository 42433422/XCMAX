"""OCR processing must use a verified session and reject spoofed identity headers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import ocr


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(ocr.router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/ocr/extract", {"json": {"text": "hello"}}),
        ("/api/ocr/analyze", {"json": {"text": "hello"}}),
        ("/api/ocr/recognize", {"files": {"image": ("sample.png", b"x", "image/png")}}),
        (
            "/api/ocr/recognize-and-extract",
            {"files": {"image": ("sample.png", b"x", "image/png")}},
        ),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"X-User-ID": "999"}, {"X-Workspace-Id": "999"}])
def test_ocr_processing_rejects_anonymous_identity(
    client: TestClient, path: str, payload: dict, headers: dict
) -> None:
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=None),
        patch.object(ocr, "_run_ocr_agent") as run,
        patch.object(ocr, "save_upload_file") as save,
    ):
        response = client.post(path, headers=headers, **payload)
    assert response.status_code == 401
    run.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize("user,status", [(SimpleNamespace(id=7, is_active=False), 403), (SimpleNamespace(id=None, is_active=True), 401)])
def test_ocr_processing_rejects_invalid_session_user(
    client: TestClient, user: SimpleNamespace, status: int
) -> None:
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch.object(ocr, "_run_ocr_agent") as run,
    ):
        response = client.post("/api/ocr/extract", json={"text": "hello"})
    assert response.status_code == status
    run.assert_not_called()


def test_ocr_run_identity_is_taken_from_session_not_headers(client: TestClient) -> None:
    user = SimpleNamespace(id=73, is_active=True)
    with (
        patch("app.infrastructure.auth.dependencies.resolve_session_user", return_value=user),
        patch.object(ocr, "_run_ocr_agent", return_value=object()) as run,
        patch.object(ocr, "_agent_node_output", return_value={"success": True}),
    ):
        response = client.post(
            "/api/ocr/extract",
            json={"text": "hello"},
            headers={"X-User-ID": "999", "X-Workspace-Id": "victim"},
        )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert run.call_args.kwargs["user_id"] == "73"
