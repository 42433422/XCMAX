from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.local_duty_graph_health import build_local_duty_graph_health
from app.fastapi_routes.xcmax_admin import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_build_local_duty_graph_health_shape() -> None:
    with (
        patch(
            "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
            return_value=frozenset({"emp-a", "emp-b"}),
        ),
        patch(
            "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
            return_value={"emp-a"},
        ),
    ):
        out = build_local_duty_graph_health()
    assert out["success"] is True
    assert out["source"] == "local"
    staffing = out["staffing"]
    assert staffing["planned_count"] == 2
    assert staffing["registered_count"] == 1
    assert staffing["missing_employees"] == ["emp-b"]


class TestLocalDutyGraphRoutes:
    def test_health_requires_login(self, client: TestClient) -> None:
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = client.get("/api/xcmax/local/duty-graph/health")
        assert resp.status_code == 401

    def test_health_ok_when_logged_in(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess",
            ),
            patch(
                "app.application.local_duty_graph_health.build_local_duty_graph_health",
                return_value={"success": True, "source": "local", "staffing": {}},
            ),
        ):
            resp = client.get("/api/xcmax/local/duty-graph/health")
        assert resp.status_code == 200
        assert resp.json()["source"] == "local"
