"""Unknown programming errors remain HTTP 500 with safe diagnostic location."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.error_handler import register_exception_handlers


def test_unknown_type_error_keeps_failure_status_and_location(caplog):
    app = FastAPI()

    @app.get("/broken")
    def broken():
        raise TypeError("private-error-marker")

    register_exception_handlers(app)
    with caplog.at_level(logging.ERROR), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/broken")

    assert response.status_code == 500
    assert response.json()["error_code"] == "internal_error"
    assert "private-error-marker" not in response.text
    assert any(
        "Unhandled TypeError" in record.message and "broken@" in record.message
        for record in caplog.records
    )
