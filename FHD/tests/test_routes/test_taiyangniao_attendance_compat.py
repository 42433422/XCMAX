from __future__ import annotations

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
