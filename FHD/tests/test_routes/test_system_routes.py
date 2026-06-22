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


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=False)


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
        with patch(
            "app.application.facades.session_facade.get_system_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/api/system/info")
            assert r.status_code == 500


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
        with patch(
            "app.application.facades.session_facade.get_system_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/api/system/printer")
            assert r.status_code == 500

    def test_post_empty_body(self, client: TestClient):
        r = client.post("/api/system/printer", json={})
        assert r.status_code == 400

    def test_post_no_printer_name(self, client: TestClient):
        r = client.post("/api/system/printer", json={"other": "value"})
        assert r.status_code == 400

    def test_post_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.set_default_printer.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.post("/api/system/printer", json={"printer_name": "HP"})
            assert r.status_code == 200

    def test_post_fail(self, client: TestClient):
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
        with patch(
            "app.application.facades.session_facade.get_system_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/api/system/startup")
            assert r.status_code == 500

    def test_post_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.enable_startup.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.post("/api/system/startup")
            assert r.status_code == 200

    def test_delete_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.disable_startup.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_system_service", return_value=mock_svc
        ):
            r = client.delete("/api/system/startup")
            assert r.status_code == 200

    def test_delete_error(self, client: TestClient):
        with patch(
            "app.application.facades.session_facade.get_system_service",
            side_effect=Exception("fail"),
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
        with patch(
            "app.application.facades.session_facade.get_database_service",
            side_effect=Exception("fail"),
        ):
            r = client.get("/api/database/backups")
            assert r.status_code == 500

    def test_backup_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.backup_database.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_database_service", return_value=mock_svc
        ):
            r = client.post("/api/database/backup")
            assert r.status_code == 200

    def test_backup_error(self, client: TestClient):
        with patch(
            "app.application.facades.session_facade.get_database_service",
            side_effect=Exception("fail"),
        ):
            r = client.post("/api/database/backup")
            assert r.status_code == 500

    def test_delete_backup_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.delete_backup.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_database_service", return_value=mock_svc
        ):
            r = client.delete("/api/database/backup/test.sql")
            assert r.status_code == 200

    def test_delete_backup_error(self, client: TestClient):
        with patch(
            "app.application.facades.session_facade.get_database_service",
            side_effect=Exception("fail"),
        ):
            r = client.delete("/api/database/backup/test.sql")
            assert r.status_code == 500

    def test_restore_missing_file(self, client: TestClient):
        r = client.post("/api/database/restore", json={})
        assert r.status_code == 400

    def test_restore_success(self, client: TestClient):
        mock_svc = MagicMock()
        mock_svc.restore_database.return_value = {"success": True}
        with patch(
            "app.application.facades.session_facade.get_database_service", return_value=mock_svc
        ):
            r = client.post("/api/database/restore", json={"backup_file": "backup.sql"})
            assert r.status_code == 200

    def test_restore_error(self, client: TestClient):
        with patch(
            "app.application.facades.session_facade.get_database_service",
            side_effect=Exception("fail"),
        ):
            r = client.post("/api/database/restore", json={"backup_file": "backup.sql"})
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# performance routes
# ---------------------------------------------------------------------------


class TestPerformanceStatus:
    def test_not_initialized(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt._initialized = False
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/status")
            assert r.status_code == 503

    def test_initialized(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt._initialized = True
        mock_opt.get_status.return_value = {"status": "ok"}
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/status")
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            side_effect=Exception("fail"),
        ):
            r = client.get("/api/performance/status")
            assert r.status_code == 500


class TestPerformanceHealth:
    def test_healthy(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.get_health_check.return_value = {"status": "healthy", "timestamp": 0, "checks": {}}
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/health")
            assert r.status_code == 200

    def test_degraded(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.get_health_check.return_value = {
            "status": "degraded",
            "timestamp": 0,
            "checks": {},
        }
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/health")
            assert r.status_code == 503

    def test_unhealthy(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.get_health_check.return_value = {
            "status": "unhealthy",
            "timestamp": 0,
            "checks": {},
        }
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/health")
            assert r.status_code == 500

    def test_with_issues(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.get_health_check.return_value = {
            "status": "healthy",
            "timestamp": 0,
            "checks": {},
            "issues": ["slow"],
        }
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/health")
            assert r.json()["issues"] == ["slow"]

    def test_error(self, client: TestClient):
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer",
            side_effect=Exception("fail"),
        ):
            r = client.get("/api/performance/health")
            assert r.status_code == 500


class TestPerformanceMetricsSummary:
    def test_no_monitor(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/metrics/summary")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor.get_metrics_summary.return_value = {"avg_ms": 100}
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/metrics/summary")
            assert r.json()["success"] is True


class TestPerformanceMetricsPrometheus:
    def test_no_monitor(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/metrics/prometheus")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor.get_prometheus_metrics.return_value = "# metrics"
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/metrics/prometheus")
            assert r.status_code == 200


class TestPerformanceCacheStats:
    def test_no_redis(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/cache/stats")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache.stats = {"hits": 100}
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/cache/stats")
            assert r.json()["success"] is True


class TestPerformanceCacheClear:
    def test_no_redis(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.post("/api/performance/cache/clear")
            assert r.status_code == 503

    def test_clear_with_pattern(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache.clear_pattern.return_value = 5
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.post("/api/performance/cache/clear?pattern=test:*")
            assert r.json()["success"] is True

    def test_clear_local(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache.clear_local_cache = MagicMock()
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.post("/api/performance/cache/clear")
            assert r.json()["success"] is True


class TestPerformanceCacheInvalidate:
    def test_empty_keys(self, client: TestClient):
        r = client.post("/api/performance/cache/invalidate", json={"keys": []})
        assert r.status_code == 400

    def test_no_redis(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.post("/api/performance/cache/invalidate", json={"keys": ["k1"]})
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.redis_cache.delete.return_value = 1
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.post("/api/performance/cache/invalidate", json={"keys": ["k1"]})
            assert r.json()["success"] is True


class TestPerformanceTasksStatus:
    def test_no_task_manager(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.async_task_manager = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/tasks/status")
            assert r.status_code == 503

    def test_task_not_found(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.async_task_manager.get_status.return_value = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
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
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/tasks/status?task_id=t1")
            assert r.json()["success"] is True

    def test_all_tasks(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.async_task_manager.active_tasks = {}
        mock_opt.async_task_manager.stats = {"total": 0}
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/tasks/status")
            assert r.json()["success"] is True


class TestPerformanceAlerts:
    def test_no_monitor(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/alerts")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.performance_monitor.get_alerts.return_value = []
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/alerts")
            assert r.json()["success"] is True


class TestPerformanceSlowQueries:
    def test_no_optimizer(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.query_optimizer = None
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/slow-queries")
            assert r.status_code == 503

    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.query_optimizer.get_slow_queries.return_value = []
        with patch(
            "app.utils.performance_initializer.get_performance_optimizer", return_value=mock_opt
        ):
            r = client.get("/api/performance/slow-queries")
            assert r.json()["success"] is True


class TestPerformanceOptimizeReinitialize:
    def test_success(self, client: TestClient):
        mock_opt = MagicMock()
        mock_opt.get_status.return_value = {"status": "ok"}
        with patch(
            "app.utils.performance_initializer.init_performance_optimization", return_value=mock_opt
        ):
            r = client.post("/api/performance/optimize/reinitialize")
            assert r.json()["success"] is True

    def test_error(self, client: TestClient):
        with patch(
            "app.utils.performance_initializer.init_performance_optimization",
            side_effect=Exception("fail"),
        ):
            r = client.post("/api/performance/optimize/reinitialize")
            assert r.status_code == 500


# ---------------------------------------------------------------------------
# templates routes
# ---------------------------------------------------------------------------


class TestTemplatesProgress:
    def test_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.system.routes.get_template_analysis_progress",
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
        assert r.status_code == 400

    def test_fs_template_empty_filename(self, client: TestClient):
        r = client.request(
            "DELETE",
            "/api/templates/delete",
            content=json.dumps({"id": "fs:"}),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    def test_fs_template_not_found(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.system.routes.get_base_dir", return_value="/nonexistent"
        ):
            r = client.request(
                "DELETE",
                "/api/templates/delete",
                content=json.dumps({"id": "fs:missing.docx"}),
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == 404

    def test_fs_template_success(self, client: TestClient, tmp_path):
        test_file = tmp_path / "test.docx"
        test_file.write_text("content")
        with patch(
            "app.fastapi_routes.domains.system.routes.get_base_dir", return_value=str(tmp_path)
        ):
            r = client.request(
                "DELETE",
                "/api/templates/delete",
                content=json.dumps({"id": "fs:test.docx"}),
                headers={"Content-Type": "application/json"},
            )
            assert r.json()["success"] is True

    def test_db_template_not_found(self, client: TestClient):
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
            assert r.status_code == 404

    def test_unsupported_type(self, client: TestClient):
        r = client.request(
            "DELETE",
            "/api/templates/delete",
            content=json.dumps({"id": "other:123"}),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    def test_error(self, client: TestClient):
        with patch(
            "app.fastapi_routes.domains.system.routes.get_base_dir",
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
    def test_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_create",
            return_value=({"success": True}, 200),
        ):
            r = client.post("/api/templates/create", json={"name": "test"})
            assert r.status_code == 200


class TestTemplatesUpdate:
    def test_success(self, client: TestClient):
        with patch(
            "app.fastapi_routes.document_templates_compat.run_archive_template_update",
            return_value=({"success": True}, 200),
        ):
            r = client.post("/api/templates/update", json={"id": 1, "name": "updated"})
            assert r.status_code == 200


class TestTemplatesDeletePost:
    def test_delegates_to_delete(self, client: TestClient):
        with patch("app.utils.path_utils.get_base_dir", return_value="/nonexistent"):
            r = client.post("/api/templates/delete", json={"id": "fs:missing.docx"})
            assert r.status_code == 404


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
        with patch("app.infrastructure.skills.get_skill_registry", side_effect=Exception("fail")):
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
    def test_success(self, client: TestClient):
        with patch(
            "app.application.facades.tools_facade.run_archive_tools_execute",
            return_value=({"success": True}, 200),
        ):
            r = client.post("/api/skills/execute", json={"skill_id": "s1"})
            assert r.status_code == 200


class TestToolsExecute:
    def test_success(self, client: TestClient):
        with patch(
            "app.application.facades.tools_facade.run_archive_tools_execute",
            return_value=({"success": True}, 200),
        ):
            r = client.post("/api/tools/execute", json={"tool_id": "t1"})
            assert r.status_code == 200


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
