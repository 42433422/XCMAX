"""Retired host conversion endpoints cannot read global customer files or data."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.legacy.routes.taiyangniao_attendance_compat import router
from app.mod_sdk.customer_features import require_attendance_conversion


def client_for(*, granted=True):
    app = FastAPI()
    app.include_router(router)
    if granted:
        app.dependency_overrides[require_attendance_conversion] = lambda: None
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("operation", ["rules", "policy", "template", "convert-upload"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_legacy_entry_delegates_to_independent_mod_preserving_method(operation, method):
    response = client_for().request(
        method, f"/api/mod/taiyangniao-pro/attendance/{operation}?month=2026-08"
    )
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == f"/api/mod/sunbird-attendance-custom/attendance/{operation}?month=2026-08"
    )


def test_anonymous_legacy_entry_remains_blocked():
    assert (
        client_for(granted=False).get("/api/mod/taiyangniao-pro/attendance/rules").status_code
        == 401
    )


def test_denied_account_never_redirects_to_custom_code():
    app = FastAPI()
    app.include_router(router)

    def deny():
        raise HTTPException(403, "custom entitlement required")

    app.dependency_overrides[require_attendance_conversion] = deny
    response = TestClient(app).post("/api/mod/taiyangniao-pro/attendance/convert-upload")
    assert response.status_code == 403


def test_old_global_output_path_is_retired():
    response = client_for().get(
        "/api/mod/taiyangniao-pro/attendance/download?relpath=customer.xlsx"
    )
    assert response.status_code == 410
    assert "location" not in response.headers
