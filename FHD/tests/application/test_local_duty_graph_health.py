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
        patch(
            "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
            return_value={
                "enabled": True,
                "running": False,
                "last_error": "",
                "jobs": [{"employee_id": "daily-orchestrator", "next_run_time": "2026-06-19T08:15:00+08:00"}],
            },
        ),
    ):
        out = build_local_duty_graph_health()
    assert out["success"] is True
    assert out["source"] == "local"
    staffing = out["staffing"]
    assert staffing["planned_count"] == 2
    assert staffing["registered_count"] == 1
    # 本地 health：缺岗走 missing_local_employee_packs；missing_employees 恒 []（与 MODstore 对齐）
    assert staffing["missing_employees"] == []
    assert staffing["missing_local_employee_packs"] == ["emp-b"]
    assert out["employee_cron_jobs"][0]["employee_id"] == "daily-orchestrator"
    assert out["employee_scheduler"]["enabled"] is True


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

    def test_employee_status_ok(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess",
            ),
            patch(
                "app.application.local_duty_graph_health.build_local_employee_status",
                return_value={
                    "employee_id": "seo-sitemap-curator",
                    "deployed": True,
                    "execution_stats": {
                        "total_executions": 0,
                        "success_count": 0,
                        "success_rate": 0,
                    },
                },
            ),
        ):
            resp = client.get("/api/xcmax/local/employees/seo-sitemap-curator/status")
        assert resp.status_code == 200
        assert resp.json()["deployed"] is True

    def test_employee_cron_jobs_ok(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess",
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_cron_jobs",
                return_value=[{"job_id": "daily-orchestrator", "employee_id": "daily-orchestrator"}],
            ),
        ):
            resp = client.get("/api/xcmax/local/employee-cron/jobs")
        assert resp.status_code == 200
        assert resp.json()["jobs"][0]["employee_id"] == "daily-orchestrator"

    def test_employee_cron_job_run_ok(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess",
            ),
            patch(
                "app.application.employee_runtime.scheduler.run_employee_cron_job",
                return_value={"success": True, "job": {"job_id": "daily-orchestrator"}, "result": {"success": True}},
            ) as run_job,
        ):
            resp = client.post(
                "/api/xcmax/local/employee-cron/jobs/daily-orchestrator/run",
                json={"task": "run now", "input_data": {"x": 1}},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert run_job.call_args.kwargs["task"] == "run now"
        assert run_job.call_args.kwargs["input_data"] == {"x": 1}

    def test_employee_execute_ok(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess",
            ),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                return_value={"success": True, "employee_id": "seo-sitemap-curator"},
            ) as execute,
        ):
            resp = client.post(
                "/api/xcmax/local/employees/seo-sitemap-curator/execute",
                json={"task": "生成 sitemap", "input_data": {"site": "https://example.com"}},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["source"] == "local"
        assert execute.call_args.args[0] == "seo-sitemap-curator"
        assert execute.call_args.args[1] == "生成 sitemap"

    def test_employee_manifest_404_when_missing(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess",
            ),
            patch(
                "app.application.local_duty_graph_health.read_local_employee_manifest",
                return_value=None,
            ),
        ):
            resp = client.get("/api/xcmax/local/employees/missing-emp/manifest")
        assert resp.status_code == 404
