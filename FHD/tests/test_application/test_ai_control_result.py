"""Business execution must not report rejected requests as completed work."""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.application.aiopen import service


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (200, {"success": True}, True),
        (201, {"id": 1}, True),
        (200, {"success": False, "message": "rejected"}, False),
        (401, {"detail": "not authenticated"}, False),
        (403, {"detail": "forbidden"}, False),
        (404, {"detail": "missing"}, False),
        (422, {"detail": "invalid"}, False),
        (500, {"detail": "failed"}, False),
    ],
)
def test_api_call_business_success(monkeypatch, status, payload, expected):
    app = FastAPI()

    @app.get("/api/control-test")
    def endpoint():
        return JSONResponse(payload, status_code=status)

    monkeypatch.setattr(service, "is_path_whitelisted", lambda path: True)
    result = service._tool_api_call(app, {"path": "/api/control-test"})
    assert result["success"] is expected
    assert result["status_code"] == status
    assert result["data"] == payload
