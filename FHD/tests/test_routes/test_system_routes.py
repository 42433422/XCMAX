"""Tests for app.fastapi_routes.domains.system.routes — system/performance/template routes with mocked dependencies."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.system import routes
from app.fastapi_routes.tools_execute import router as tools_execute_router
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _assert_shared_error_0(self, client, _shared_literal_0, _shared_literal_1):
    with patch(_shared_literal_0, side_effect=RuntimeError("fail")):
        r = client.get(_shared_literal_1)
        assert r.status_code == 500


def _assert_shared_healthy_1(self, client, _shared_literal_0, _shared_literal_1):
    mock_opt = MagicMock()
    mock_opt.get_health_check.return_value = {
        "status": _shared_literal_0,
        "timestamp": 0,
        "checks": {},
    }
    with patch(
        "app.utils.performance.performance_initializer.get_performance_optimizer",
        return_value=mock_opt,
    ):
        r = client.get("/api/performance/health")
        assert r.status_code == _shared_literal_1


def _assert_mock_maintenance_unverified(client, payload, action):
    """A service mock proves dispatch, not the resulting host/cache/database state."""
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_inconclusive"
    assert payload["verification_code"] == "result_verifier_unavailable"
    assert payload["outcome"] == "unknown"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert payload["run_id"] == payload["agent_run_id"]
    run = client.app.state.agent_runs.get(payload["run_id"])
    assert run is not None and run.status == "blocked"
    assert len(run.tool_calls) == 1
    call = run.tool_calls[0]
    assert (call.tool_id, call.action) == ("system_maintenance", action)
    assert call.output["success"] is True
    report = call.metadata["verification"]
    assert report["status"] == "inconclusive" and report["accepted"] is False
    assert report["code"] == "result_verifier_unavailable"
    assert all(check["status"] != "passed" for check in report["checks"])
    assert run.steps[0].attempt_count == 1
    assert not {"tool.completed", "run.completed"} & {event.event_type for event in run.events}
    return run


def _assert_registered_read_route(client, path, identifier_key):
    """Exercise the actual registered read contract through either public entry."""
    service = MagicMock()
    service.get_all.return_value = {
        "success": True,
        "data": [{"id": 1, "customer_name": "ACME"}],
        "total": 1,
    }
    with patch("app.application.get_customer_app_service", return_value=service):
        response = client.post(
            path,
            json={
                identifier_key: "customers",
                "action": "query",
                "params": {"keyword": "ACME"},
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True and payload["agent_status"] == "completed"
    assert payload["data"] == [{"id": 1, "customer_name": "ACME"}]
    service.get_all.assert_called_once_with(keyword="ACME", page=1, per_page=20)
    run = client.app.state.agent_runs.get(payload["run_id"])
    assert run is not None and len(run.tool_calls) == 1
    call = run.tool_calls[0]
    assert (call.tool_id, call.action) == ("customers", "query")
    assert call.metadata["verification"]["accepted"] is True
    assert call.metadata["verification"]["code"] == "read_only_output_contract_checked"


@pytest.fixture
def client(trusted_actor, local_tools, monkeypatch, tmp_path) -> TestClient:
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-idempotency.sqlite"))
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XCAGI_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    app = FastAPI()
    app.state.agent_runs = repo
    app.include_router(routes.router)
    app.include_router(tools_execute_router)
    return TestClient(
        app, raise_server_exceptions=False, headers=trusted_actor(role="admin").headers
    )


# ---------------------------------------------------------------------------
# system_config_get
# ---------------------------------------------------------------------------


class TestSystemConfigGet:
    def test_returns_data(self, client: TestClient):
        r = client.get("/api/system/config")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "data" in data


# ---------------------------------------------------------------------------
# system_info_get
# ---------------------------------------------------------------------------


class TestSystemInfoGet:
    def test_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_system_info.return_value = {"version": "10.0.0"}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.get("/api/system/info")
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        return _assert_shared_error_0(
            self,
            client,
            "app.application.facades.session_facade.get_system_service",
            "/api/system/info",
        )


# ---------------------------------------------------------------------------
# system_printer_get / system_printer_post
# ---------------------------------------------------------------------------


class TestSystemPrinter:
    def test_get_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_printer_config.return_value = {"default": "HP"}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.get("/api/system/printer")
            assert r.json()["success"] is True

    def test_get_error(self, client: TestClient):
        return _assert_shared_error_0(
            self,
            client,
            "app.application.facades.session_facade.get_system_service",
            "/api/system/printer",
        )

    def test_post_empty_body(self, client: TestClient):
        r = client.post("/api/system/printer", json={})
        assert r.status_code == 400

    def test_post_no_printer_name(self, client: TestClient):
        r = client.post("/api/system/printer", json={"other": "value"})
        assert r.status_code == 400

    def test_post_success(self, client: TestClient, local_tools):
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.post("/api/system/printer", json={"printer_name": "HP"})
            assert r.status_code == 200
        mock_svc.set_default_printer.assert_called_once_with("HP")

    def test_post_fail(self, client: TestClient, local_tools):
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": False, "message": "error"}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.post("/api/system/printer", json={"printer_name": "HP"})
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# system_startup_get / post / delete
# ---------------------------------------------------------------------------


class TestSystemStartup:
    def test_get_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.get_startup_config.return_value = {"enabled": False}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.get("/api/system/startup")
            assert r.json()["success"] is True

    def test_get_error(self, client: TestClient):
        return _assert_shared_error_0(
            self,
            client,
            "app.application.facades.session_facade.get_system_service",
            "/api/system/startup",
        )

    def test_post_success(self, client: TestClient, local_tools):
        mock_svc = MagicMock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.post("/api/system/startup")
            assert r.status_code == 200
        mock_svc.enable_startup.assert_called_once_with()

    def test_delete_success(self, client: TestClient, local_tools):
        mock_svc = MagicMock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.delete("/api/system/startup")
            assert r.status_code == 200
        mock_svc.disable_startup.assert_called_once_with()

    def test_delete_error(self, client: TestClient):
        with patch(
            "app.application.facades.session_facade.get_system_service",
            side_effect=RuntimeError("fail"),
        ):
            r = client.delete("/api/system/startup")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# database backups
# ---------------------------------------------------------------------------


class TestDatabaseBackups:
    def test_list_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.list_backups.return_value = {"success": True, "data": []}
        with patch(
            "app.application.facades.session_facade.get_database_service", return_value=mock_svc
        ):
            r = client.get("/api/database/backups")
            assert r.json()["success"] is True

    def test_list_error(self, client: TestClient):
        return _assert_shared_error_0(
            self,
            client,
            "app.application.facades.session_facade.get_database_service",
            "/api/database/backups",
        )

    def test_backup_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.backup_database.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_database_service", return_value=mock_svc
        ):
            r = client.post("/api/database/backup")
            assert r.status_code == 200
        mock_svc.backup_database.assert_called_once_with()

    def test_backup_error(self, client: TestClient, local_tools):
        with patch(
            "app.application.facades.session_facade.get_database_service",
            side_effect=RuntimeError("fail"),
        ):
            r = client.post("/api/database/backup")
            assert r.status_code == 500

    @pytest.mark.parametrize("action", ["delete", "restore"])
    def test_destructive_backup_action_requires_approval(self, client: TestClient, action):
        service = MagicMock()
        with patch(
            "app.application.facades.session_facade.get_database_service", return_value=service
        ):
            response = (
                client.delete("/api/database/backup/test.sql")
                if action == "delete"
                else client.post("/api/database/restore", json={"backup_file": "backup.sql"})
            )
        assert response.status_code == 202
        assert response.json()["error_code"] == "approval_required"
        service.delete_backup.assert_not_called()
        service.restore_database.assert_not_called()

    def test_restore_missing_file(self, client: TestClient):
        r = client.post("/api/database/restore", json={})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# performance routes
# ---------------------------------------------------------------------------


class TestPerformanceStatus:
    def test_not_initialized(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt._initialized = False
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/status")
            assert r.status_code == 503

    def test_initialized(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt._initialized = True
        mock_opt.get_status.return_value = {"status": "ok"}
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/status")
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        return _assert_shared_error_0(
            self,
            client,
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            "/api/performance/status",
        )


class TestPerformanceHealth:
    def test_healthy(self, client: TestClient):
        return _assert_shared_healthy_1(self, client, "healthy", 200)

    def test_degraded(self, client: TestClient):
        return _assert_shared_healthy_1(self, client, "degraded", 503)

    def test_unhealthy(self, client: TestClient):
        return _assert_shared_healthy_1(self, client, "unhealthy", 500)

    def test_with_issues(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.get_health_check.return_value = {
            "status": "healthy",
            "timestamp": 0,
            "checks": {},
            "issues": ["slow"],
        }
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/health")
            assert r.json()["issues"] == ["slow"]

    def test_error(self, client: TestClient):
        return _assert_shared_error_0(
            self,
            client,
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            "/api/performance/health",
        )


class TestPerformanceMetricsSummary:
    def test_no_monitor(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/metrics/summary")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor.get_metrics_summary.return_value = {"avg_ms": 100}
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/metrics/summary")
            assert r.json()["success"] is True


class TestPerformanceMetricsPrometheus:
    def test_no_monitor(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/metrics/prometheus")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor.get_prometheus_metrics.return_value = "# metrics"
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/metrics/prometheus")
            assert r.status_code == 200


class TestPerformanceCacheStats:
    def test_no_redis(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/cache/stats")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache.stats = {"hits": 100}
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/cache/stats")
            assert r.json()["success"] is True


class TestPerformanceCacheClear:
    def test_no_redis(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.post("/api/performance/cache/clear")
            assert r.status_code == 503

    def test_clear_with_pattern(self, client: TestClient, local_tools):
        mock_opt = MagicMock()
        mock_opt.redis_cache.clear_pattern.return_value = 5
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.post("/api/performance/cache/clear?pattern=test:*")
            assert r.status_code == 200
            _assert_mock_maintenance_unverified(client, r.json(), "clear_performance_cache")
        mock_opt.redis_cache.clear_pattern.assert_called_once_with("test:*")

    def test_clear_local(self, client: TestClient, local_tools):
        mock_opt = MagicMock()
        mock_opt.redis_cache.clear_local_cache = MagicMock()
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.post("/api/performance/cache/clear")
            assert r.status_code == 200
            _assert_mock_maintenance_unverified(client, r.json(), "clear_performance_cache")
        mock_opt.redis_cache.clear_local_cache.assert_called_once_with()


class TestPerformanceCacheInvalidate:
    def test_empty_keys(self, client: TestClient):
        r = client.post("/api/performance/cache/invalidate", json={"keys": []})
        assert r.status_code == 400

    def test_no_redis(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.post("/api/performance/cache/invalidate", json={"keys": ["k1"]})
            assert r.status_code == 503

    def test_success(self, client: TestClient, local_tools):
        mock_opt = MagicMock()
        mock_opt.redis_cache.delete.return_value = 1
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.post("/api/performance/cache/invalidate", json={"keys": ["k1"]})
            assert r.status_code == 200
            _assert_mock_maintenance_unverified(client, r.json(), "invalidate_performance_cache")
            assert r.json()["data"]["deleted_count"] == 1
        mock_opt.redis_cache.delete.assert_called_once_with("k1")


class TestPerformanceTasksStatus:
    def test_no_task_manager(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.async_task_manager = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/tasks/status")
            assert r.status_code == 503

    def test_task_not_found(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.async_task_manager.get_status.return_value = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/tasks/status?task_id=bad")
            assert r.status_code == 404

    def test_task_found(self, client: TestClient):
        mock_result = MagicMock()
        mock_result.task_id = "t1"
        mock_result.status.value = "running"
        mock_result.progress = 0.5
        mock_result.duration_ms = 100.0
        mock_result.error = None
        mock_result.metadata = {"task_name": "test"}
        mock_opt = MagicMock()
        mock_opt.async_task_manager.get_status.return_value = mock_result
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/tasks/status?task_id=t1")
            assert r.json()["success"] is True

    def test_all_tasks(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.async_task_manager.active_tasks = {}
        mock_opt.async_task_manager.stats = {"total": 0}
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/tasks/status")
            assert r.json()["success"] is True


class TestPerformanceAlerts:
    def test_no_monitor(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/alerts")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor.get_alerts.return_value = []
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/alerts")
            assert r.json()["success"] is True


class TestPerformanceSlowQueries:
    def test_no_optimizer(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.query_optimizer = None
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/slow-queries")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.query_optimizer.get_slow_queries.return_value = []
        with patch(
            "app.utils.performance.performance_initializer.get_performance_optimizer",
            return_value=mock_opt,
        ):
            r = client.get("/api/performance/slow-queries")
            assert r.json()["success"] is True


class TestPerformanceOptimizeReinitialize:
    def test_reinitialize_requires_approval(self, client: TestClient):
        with patch(
            "app.utils.performance.performance_initializer.init_performance_optimization"
        ) as init:
            response = client.post("/api/performance/optimize/reinitialize")
        assert response.status_code == 202
        assert response.json()["error_code"] == "approval_required"
        init.assert_not_called()


# ---------------------------------------------------------------------------
# templates routes
# ---------------------------------------------------------------------------


def _assert_template_receipt(response, client, action, legacy_status, *, raw_success=False):
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["success"] is False and body["agent_status"] == "blocked"
    run = client.app.state.agent_runs.get(body["run_id"])
    assert run is not None and run.status == "blocked" and len(run.tool_calls) == 1
    call = run.tool_calls[0]
    assert call.tool_id == "document_template" and call.action == action
    assert call.output["success"] is raw_success
    assert call.output["http_status_code"] == legacy_status
    report = call.metadata["verification"]
    assert report["accepted"] is False
    assert report["code"] == (
        "result_template_receipt_unavailable" if raw_success else "execution_receipt_not_successful"
    )
    if raw_success:
        assert body["error_code"] == "result_verification_inconclusive"
        assert body["retryable"] is False and body["reconciliation_required"] is True
    assert not {"tool.completed", "run.completed"} & {event.event_type for event in run.events}
    return call


class TestTemplatesProgress:
    def test_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.system.system_routes.get_template_analysis_progress",
            return_value={
                "progress": 50,
                "success": True,
                "task_id": "task1",
                "step": 1,
                "message": "done",
                "completed": False,
            },
        ):
            r = client.get("/api/templates/progress/task1")
            assert r.json()["progress"] == 50


class TestTemplatesDelete:
    def test_missing_id(self, client: TestClient):
        r = client.request(
            "DELETE",
            "/api/templates/delete",
            content=json.dumps({}),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400, r.text

    def test_fs_template_empty_filename(self, client: TestClient):
        r = client.request(
            "DELETE",
            "/api/templates/delete",
            content=json.dumps({"id": "fs:"}),
            headers={"Content-Type": "application/json"},
        )
        call = _assert_template_receipt(r, client, "delete", 400)
        assert call.output["message"] == "模板文件名无效"

    def test_fs_template_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.system.system_routes.get_base_dir",
            return_value="/nonexistent",
        ):
            r = client.request(
                "DELETE",
                "/api/templates/delete",
                content=json.dumps({"id": "fs:missing.docx"}),
                headers={"Content-Type": "application/json"},
            )
            call = _assert_template_receipt(r, client, "delete", 404)
            assert "模板文件不存在" in call.output["message"]

    def test_builtin_fs_template_is_refused_and_preserved(self, client: TestClient, tmp_path):
        test_file = tmp_path / "test.docx"
        test_file.write_text("content")
        with patch(
            "app.fastapi_routes.domains.system.system_routes.get_base_dir",
            return_value=str(tmp_path),
        ):
            r = client.request(
                "DELETE",
                "/api/templates/delete",
                content=json.dumps({"id": "fs:test.docx"}),
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == 403, r.text
            assert r.json()["success"] is False
            assert test_file.read_text() == "content"

    def test_db_template_not_found(self, client: TestClient, local_tools):
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        with (
            patch("app.db.session.get_db", return_value=mock_db),
            patch("app.db.init_db.init_template_tables"),
        ):
            r = client.request(
                "DELETE",
                "/api/templates/delete",
                content=json.dumps({"id": "db:9999"}),
                headers={"Content-Type": "application/json"},
            )
            call = _assert_template_receipt(r, client, "delete", 404)
            assert call.output["message"] == "模板不存在"
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_not_called()

    def test_unsupported_type(self, client: TestClient):
        r = client.request(
            "DELETE",
            "/api/templates/delete",
            content=json.dumps({"id": "other:123"}),
            headers={"Content-Type": "application/json"},
        )
        call = _assert_template_receipt(r, client, "delete", 400)
        assert "暂不支持删除该模板类型" in call.output["message"]

    def test_error(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.system.system_routes.get_base_dir",
            side_effect=RuntimeError("fail"),
        ):
            r = client.request(
                "DELETE",
                "/api/templates/delete",
                content=json.dumps({"id": "fs:test.docx"}),
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == 500


class TestTemplatesCreate:
    def test_success(self, client: TestClient, local_tools):
        with patch(
            "app.legacy.routes.document_templates_compat.run_archive_template_create",
            return_value=({"success": True}, 200),
        ) as create:
            r = client.post("/api/templates/create", json={"name": "test"})
        _assert_template_receipt(r, client, "create", 200, raw_success=True)
        create.assert_called_once_with({"name": "test"})


class TestTemplatesUpdate:
    def test_success(self, client: TestClient, local_tools):
        with patch(
            "app.legacy.routes.document_templates_compat.run_archive_template_update",
            return_value=({"success": True}, 200),
        ) as update:
            r = client.post("/api/templates/update", json={"id": 1, "name": "updated"})
        _assert_template_receipt(r, client, "update", 200, raw_success=True)
        update.assert_called_once_with({"id": 1, "name": "updated"})


class TestTemplatesDeletePost:
    def test_delegates_to_delete(self, client: TestClient):
        with patch("app.utils.path_io.path_utils.get_base_dir", return_value="/nonexistent"):
            r = client.post("/api/templates/delete", json={"id": "fs:missing.docx"})
        call = _assert_template_receipt(r, client, "delete", 404)
        assert call.params == {"id": "fs:missing.docx"}


# ---------------------------------------------------------------------------
# skills routes
# ---------------------------------------------------------------------------


class TestSkillsList:
    def test_success(self, client: TestClient):
        mock_reg = MagicMock()
        mock_reg.list_all.return_value = [{"id": "s1"}]
        with patch("app.infrastructure.skills.get_skill_registry", return_value=mock_reg):
            r = client.get("/api/skills/list")
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        with patch(
            "app.infrastructure.skills.get_skill_registry", side_effect=RuntimeError("fail")
        ):
            r = client.get("/api/skills/list")
            assert r.status_code == 500


class TestSkillsInfo:
    def test_found(self, client: TestClient):
        mock_reg = MagicMock()
        mock_reg.get.return_value = {
            "name": "test",
            "description": "desc",
            "keywords": [],
            "category": "gen",
        }
        with patch("app.infrastructure.skills.get_skill_registry", return_value=mock_reg):
            r = client.get("/api/skills/info/s1")
            assert r.json()["success"] is True

    def test_not_found(self, client: TestClient):
        mock_reg = MagicMock()
        mock_reg.get.return_value = None
        with patch("app.infrastructure.skills.get_skill_registry", return_value=mock_reg):
            r = client.get("/api/skills/info/missing")
            assert r.status_code == 404


class TestSkillsExecute:
    def test_success(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
        _assert_registered_read_route(client, "/api/skills/execute", "skill_id")

    def test_unregistered_skill_is_rejected(self, client: TestClient):
        with patch(
            "app.application.facades.tools_facade.run_archive_tools_execute",
            return_value=({"success": True}, 200),
        ) as legacy_execute:
            r = client.post("/api/skills/execute", json={"skill_id": "s1"})
        assert r.status_code == 400
        assert r.json()["error_code"] == "tool_contract_unavailable"
        assert r.json()["execution_status"] == "not_started"
        assert r.json()["retryable"] is False
        legacy_execute.assert_not_called()
        assert not client.app.state.agent_runs.list_recent()


class TestToolsExecute:
    def test_success(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
        _assert_registered_read_route(client, "/api/tools/execute", "tool_id")

    def test_unregistered_tool_is_rejected(self, client: TestClient):
        with patch(
            "app.application.facades.tools_facade.run_archive_tools_execute",
            return_value=({"success": True}, 200),
        ) as legacy_execute:
            r = client.post("/api/tools/execute", json={"tool_id": "t1"})
        assert r.status_code == 400
        assert r.json()["error_code"] == "tool_contract_unavailable"
        assert r.json()["execution_status"] == "not_started"
        assert r.json()["retryable"] is False
        legacy_execute.assert_not_called()
        assert not client.app.state.agent_runs.list_recent()


# ---------------------------------------------------------------------------
# admin_llm_reload
# ---------------------------------------------------------------------------


class TestAdminLlmReload:
    def test_success(self, client: TestClient):
        import app.infrastructure.llm.providers.registry as reg_mod

        old_registry = reg_mod._registry
        with patch.object(reg_mod, "_registry", None):
            r = client.post("/api/admin/llm/reload")
            assert r.json()["success"] is True


def test_maintenance_denial_uses_signed_actor_and_never_calls_service(client, trusted_actor):
    client.headers.update(trusted_actor(role="user").headers)
    service = MagicMock()
    with patch("app.application.facades.session_facade.get_system_service", return_value=service):
        response = client.post("/api/system/printer", json={"printer_name": "HP"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "tool_permission_denied"
    service.set_default_printer.assert_not_called()


def test_maintenance_admin_can_execute_with_own_identity(client, trusted_actor):
    admin = trusted_actor(role="admin")
    client.headers.update(admin.headers)
    service = MagicMock()
    service.set_default_printer.return_value = {"success": True}
    with patch("app.application.facades.session_facade.get_system_service", return_value=service):
        response = client.post("/api/system/printer", json={"printer_name": "HP"})
    assert response.status_code == 200, response.text
    run = _assert_mock_maintenance_unverified(client, response.json(), "set_default_printer")
    assert run.user_id == str(admin.user_id)
    service.set_default_printer.assert_called_once_with("HP")


def test_restore_waits_for_approval_even_for_applicant_admin(client, trusted_actor, monkeypatch):
    admin = trusted_actor(role="admin")
    client.headers.update(admin.headers)
    from sqlalchemy import text

    from app.application.approval_workspace_app_service import approve_request
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setattr("app.db.session.SessionLocal", admin.factory)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.get_agent_run_repository",
        lambda: client.app.state.agent_runs,
    )
    service = MagicMock()
    service.restore_database.return_value = {"success": True}
    with patch("app.application.facades.session_facade.get_database_service", return_value=service):
        response = client.post("/api/database/restore", json={"backup_file": "test.sql"})
        assert response.status_code == 202, response.text
        assert response.json()["error_code"] == "approval_required"
        service.restore_database.assert_not_called()
        with admin.factory() as db:
            row = db.execute(
                text("SELECT id, applicant_id, tenant_id FROM approval_requests")
            ).one()
            assert (row.applicant_id, row.tenant_id) == (admin.user_id, admin.tenant_id)
        with tenant_scope(admin.tenant_id):
            from app.application.agent_orchestrator import AgentOrchestrator

            current = AgentOrchestrator().get_run(response.json()["run_id"])
            assert current is not None and current.status == "waiting_user", current
            receipt = approve_request(row.id, admin.request, body={}, x_user_id=None)
        if hasattr(receipt, "body"):
            receipt = json.loads(receipt.body)
        assert receipt["success"] is False
        run = client.app.state.agent_runs.get(response.json()["run_id"])
        assert run is not None and run.status == "blocked"
        assert run.user_id == str(admin.user_id)
        assert len(run.tool_calls) == 1
        call = run.tool_calls[0]
        assert (call.tool_id, call.action) == ("system_maintenance", "restore_database")
        assert call.output["success"] is True
        report = call.metadata["verification"]
        assert report["status"] == "inconclusive" and report["accepted"] is False
        assert report["code"] == "result_verifier_unavailable"
        assert all(check["status"] != "passed" for check in report["checks"])
        assert not {"tool.completed", "run.completed"} & {event.event_type for event in run.events}
        assert "durable_workflow_snapshot" not in receipt["data"]["business_data"]
        assert "_actor_authorization" not in json.dumps(receipt)
        with tenant_scope(admin.tenant_id):
            repeated = approve_request(row.id, admin.request, body={}, x_user_id=None)
        if hasattr(repeated, "body"):
            repeated = json.loads(repeated.body)
        assert repeated["success"] is False
        service.restore_database.assert_called_once_with("test.sql")
