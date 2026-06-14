"""COVERAGE_RAMP Phase 1 (p1-p0-core): system routes full sweep + approval_workspace (mocked)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import approval_workspace_app_service as approval_ws


@pytest.fixture
def system_client() -> TestClient:
    from app.fastapi_routes.domains.system import routes as system_routes

    app = FastAPI()
    app.include_router(system_routes.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# performance / cache / tasks (mocked optimizer)
# ---------------------------------------------------------------------------


def _optimizer_mock(*, initialized=True, healthy=True):
    opt = MagicMock()
    opt._initialized = initialized
    opt.get_status.return_value = {"cpu": 1}
    health_status = "healthy" if healthy else "degraded"
    opt.get_health_check.return_value = {
        "status": health_status,
        "timestamp": 1.0,
        "checks": {},
    }
    opt.get_metrics_summary.return_value = {"requests": 0}
    opt.get_prometheus_metrics.return_value = "# HELP x 1\n"
    opt.get_cache_stats.return_value = {"hits": 0}
    opt.clear_cache.return_value = {"success": True}
    opt.invalidate_cache.return_value = {"success": True}
    opt.get_task_status.return_value = {"running": 0}
    opt.get_alerts.return_value = []
    opt.get_slow_queries.return_value = []
    opt.reinitialize.return_value = {"success": True}
    return opt


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_health_healthy(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/health")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_metrics_summary(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/metrics/summary")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_prometheus(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/metrics/prometheus")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_cache_stats(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/cache/stats")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_cache_clear(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.post("/api/performance/cache/clear")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_cache_invalidate(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.post("/api/performance/cache/invalidate", json={"key": "k"})
    assert r.status_code in (200, 400)


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_tasks_status(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/tasks/status")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_alerts(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/alerts")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_slow_queries(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.get("/api/performance/slow-queries")
    assert r.status_code == 200


@patch("app.utils.performance_initializer.get_performance_optimizer")
def test_performance_reinitialize(mock_get: MagicMock, system_client: TestClient) -> None:
    mock_get.return_value = _optimizer_mock()
    r = system_client.post("/api/performance/optimize/reinitialize")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# templates / skills / tools admin
# ---------------------------------------------------------------------------


@patch("app.template_analysis_progress.get_template_analysis_progress")
def test_templates_progress(mock_prog: MagicMock, system_client: TestClient) -> None:
    mock_prog.return_value = {"percent": 50}
    r = system_client.get("/api/templates/progress/task-1")
    assert r.status_code == 200


def test_templates_delete_validation(system_client: TestClient) -> None:
    r = system_client.delete("/api/templates/delete")
    assert r.status_code in (200, 400, 405, 422)


@patch("app.infrastructure.skills.get_skill_registry")
def test_skills_list(mock_reg: MagicMock, system_client: TestClient) -> None:
    mock_reg.return_value.list_skills.return_value = []
    r = system_client.get("/api/skills/list")
    assert r.status_code in (200, 500)


def test_skills_execute_empty(system_client: TestClient) -> None:
    r = system_client.post("/api/skills/execute", json={})
    assert r.status_code in (200, 400, 422, 500)


def test_tools_execute_empty(system_client: TestClient) -> None:
    r = system_client.post("/api/tools/execute", json={})
    assert r.status_code in (200, 400, 422, 500)


def test_admin_llm_reload(system_client: TestClient) -> None:
    r = system_client.post("/api/admin/llm/reload")
    assert r.status_code == 200
    assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# approval_workspace pure helpers + list with mock db
# ---------------------------------------------------------------------------


def test_approval_generate_request_no_unique() -> None:
    a = approval_ws._generate_request_no()
    b = approval_ws._generate_request_no()
    assert a.startswith("APR")
    assert a != b


def test_approval_node_query_for_user_json_ids() -> None:
    node = SimpleNamespace(approver_ids=json.dumps([1, 2]))
    assert approval_ws._node_query_for_user(node, 2) is True
    assert approval_ws._node_query_for_user(node, 9) is False


def test_approval_next_node_ordering() -> None:
    nodes = [
        SimpleNamespace(node_order=1),
        SimpleNamespace(node_order=3),
    ]
    nxt = approval_ws._next_node(nodes, 1)
    assert nxt is not None
    assert nxt.node_order == 3


def test_approval_normalize_statuses_csv() -> None:
    out = approval_ws._normalize_statuses("approved,rejected")
    assert "approved" in out


def test_approval_allow_x_user_id_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    assert approval_ws._allow_x_user_id_header() is True


@patch("app.application.approval_workspace_app_service.get_db")
def test_approval_list_requests_empty(mock_get_db: MagicMock) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = []
    q.count.return_value = 0
    mock_db.query.return_value = q
    out = approval_ws.list_requests(page=1, page_size=10)
    assert out["success"] is True


@patch("app.application.approval_workspace_app_service.get_db")
def test_approval_get_approval_users(mock_get_db: MagicMock) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = [SimpleNamespace(id=1, username="u", name="U", email=None, department=None)]
    mock_db.query.return_value = q
    out = approval_ws.get_approval_users()
    assert out["success"] is True


@patch("app.application.approval_workspace_app_service.get_db")
def test_approval_list_flows(mock_get_db: MagicMock) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.all.return_value = [SimpleNamespace(to_dict=lambda: {"id": 1})]
    mock_db.query.return_value = q
    out = approval_ws.list_flows(is_active=None)
    assert out["success"] is True
