"""Tests for app.fastapi_routes.health_k8s — coverage ramp C3.3-a.

Covers the four health endpoints:
* ``/health/liveness`` — always 200.
* ``/health/readiness`` — 200 when all healthy, 503 when any unhealthy.
* ``/health/details`` — returns system info.
* ``/api/diagnostics/capabilities`` — full payload with intent_engines.

Plus the underlying ``_check_*`` helpers with mocked dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.health_k8s import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestLiveness:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get("/health/liveness")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "alive"
        assert "timestamp" in data
        assert "python_version" in data


class TestReadiness:
    def test_all_healthy_returns_200(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_database", return_value={"status": "healthy"}
            ),
            patch("app.fastapi_routes.health_k8s._check_redis", return_value={"status": "healthy"}),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy"},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu", return_value={"status": "healthy"}
            ),
        ):
            r = client.get("/health/readiness")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_unhealthy_returns_503(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_database",
                return_value={"status": "unhealthy", "error": "db down"},
            ),
            patch("app.fastapi_routes.health_k8s._check_redis", return_value={"status": "healthy"}),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy"},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector", return_value={"status": "disabled"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu", return_value={"status": "healthy"}
            ),
        ):
            r = client.get("/health/readiness")
        assert r.status_code == 503
        assert r.json()["status"] == "not_ready"

    def test_disabled_check_is_acceptable(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_database", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_redis", return_value={"status": "disabled"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy"},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu", return_value={"status": "healthy"}
            ),
        ):
            r = client.get("/health/readiness")
        assert r.status_code == 200


class TestDetails:
    def test_returns_system_info(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_database", return_value={"status": "healthy"}
            ),
            patch("app.fastapi_routes.health_k8s._check_redis", return_value={"status": "healthy"}),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy"},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu", return_value={"status": "healthy"}
            ),
            patch("app.fastapi_routes.health_k8s.psutil.cpu_percent", return_value=10.0),
            patch("app.fastapi_routes.health_k8s.psutil.virtual_memory") as vm,
            patch("app.fastapi_routes.health_k8s.psutil.disk_usage") as du,
        ):
            vm.return_value.percent = 50.0
            vm.return_value.available = 4 * 1024 * 1024 * 1024
            du.return_value.percent = 60.0
            r = client.get("/health/details")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["version"] == "3.0.0"
        assert data["system"]["cpu_percent"] == 10.0
        assert data["system"]["memory_percent"] == 50.0

    def test_details_disk_failure_returns_zero(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_database", return_value={"status": "healthy"}
            ),
            patch("app.fastapi_routes.health_k8s._check_redis", return_value={"status": "healthy"}),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy"},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s.psutil.disk_usage", side_effect=Exception("disk err")
            ),
            patch("app.fastapi_routes.health_k8s.psutil.cpu_percent", return_value=0),
            patch("app.fastapi_routes.health_k8s.psutil.virtual_memory") as vm,
        ):
            vm.return_value.percent = 0
            vm.return_value.available = 0
            r = client.get("/health/details")
        assert r.status_code == 200
        assert r.json()["system"]["disk_percent"] == 0.0


class TestCapabilities:
    def test_returns_full_payload(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu",
                return_value={"status": "healthy", "available": True},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector",
                return_value={"status": "healthy", "extension_version": "0.5.0"},
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy", "engines": {}},
            ),
            patch("app.fastapi_routes.health_k8s.get_unified_intent_recognizer") as g,
        ):
            rec = MagicMock()
            rec.get_engine_status.return_value = {"rule": True, "bert": False}
            g.return_value = rec
            r = client.get("/api/diagnostics/capabilities")
        assert r.status_code == 200
        data = r.json()
        assert data["rasa"]["status"] == "healthy"
        assert data["intent_engines"]["rule"] is True

    def test_capabilities_intent_engine_error(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.health_k8s._check_rasa_nlu", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_pgvector", return_value={"status": "healthy"}
            ),
            patch(
                "app.fastapi_routes.health_k8s._check_ai_service",
                return_value={"status": "healthy"},
            ),
            patch(
                "app.fastapi_routes.health_k8s.get_unified_intent_recognizer",
                side_effect=Exception("boot fail"),
            ),
        ):
            r = client.get("/api/diagnostics/capabilities")
        assert r.status_code == 200
        assert "error" in r.json()["intent_engines"]


class TestCheckHelpers:
    def test_check_database_healthy(self) -> None:
        from app.fastapi_routes.health_k8s import _check_database

        with patch("app.fastapi_routes.health_k8s.get_db") as gdb:
            gdb.return_value.__enter__.return_value.execute.return_value = None
            out = _check_database()
        assert out["status"] == "healthy"

    def test_check_database_unhealthy(self) -> None:
        from app.fastapi_routes.health_k8s import _check_database

        with patch("app.fastapi_routes.health_k8s.get_db", side_effect=Exception("db err")):
            out = _check_database()
        assert out["status"] == "unhealthy"

    def test_check_pgvector_disabled_no_url(self) -> None:
        from app.fastapi_routes.health_k8s import _check_pgvector

        with patch.dict("os.environ", {}, clear=True):
            out = _check_pgvector()
        assert out["status"] == "disabled"

    def test_check_pgvector_non_postgres(self) -> None:
        from app.fastapi_routes.health_k8s import _check_pgvector

        with patch.dict("os.environ", {"VECTOR_DB_URL": "sqlite:///test.db"}):
            out = _check_pgvector()
        assert out["status"] == "disabled"
        assert out["dialect"] == "sqlite"
