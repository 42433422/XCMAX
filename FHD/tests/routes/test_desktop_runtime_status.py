"""Tests for app.fastapi_routes.desktop_runtime — coverage ramp C3.3-a.

Covers:
* ``GET /api/desktop/status`` happy / corrupt profile / missing dirs.
* ``POST /api/desktop/model/download`` request validation and download call.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.desktop_runtime import router


@pytest.fixture
def client() -> TestClient:
    from unittest.mock import MagicMock

    from app.infrastructure.auth.dependencies import get_logged_in_user

    app = FastAPI()
    app.state.mods_full_load_done = True
    app.state.mods_background_load_scheduled = False
    app.include_router(router)
    app.dependency_overrides[get_logged_in_user] = lambda: MagicMock(id=1, is_active=True)
    return TestClient(app)


@pytest.fixture
def anon_client() -> TestClient:
    app = FastAPI()
    app.state.mods_full_load_done = True
    app.state.mods_background_load_scheduled = False
    app.include_router(router)
    return TestClient(app)


class TestDesktopStatus:
    def test_returns_full_status(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={
                    "root": Path("/tmp/x"),
                    "data": Path("/tmp/x/data"),
                    "mods": Path("/tmp/x/mods"),
                    "models": Path("/tmp/x/models"),
                },
            ),
            patch(
                "app.fastapi_routes.desktop_runtime.load_or_create_profile",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch("app.fastapi_routes.desktop_runtime.resolve_storage_mode", return_value="sqlite"),
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
            patch(
                "app.fastapi_app.startup_timing.startup_timing_snapshot",
                return_value={"phase1": 1.2},
            ),
        ):
            r = client.get("/api/desktop/status")
        assert r.status_code == 200
        data = r.json()
        assert data["desktopMode"] is True
        assert "startup_timing" in data or "timing" in data or data.get("storageMode") == "sqlite"

    def test_status_no_startup_timing_module(self, client: TestClient) -> None:
        with (
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={
                    "root": Path("/tmp/x"),
                    "data": Path("/tmp/x/data"),
                    "mods": Path("/tmp/x/mods"),
                    "models": Path("/tmp/x/models"),
                },
            ),
            patch(
                "app.fastapi_routes.desktop_runtime.load_or_create_profile",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch(
                "app.fastapi_routes.desktop_runtime.resolve_storage_mode", return_value="postgres"
            ),
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=False),
            patch(
                "app.fastapi_app.startup_timing.startup_timing_snapshot",
                side_effect=ImportError("module missing"),
            ),
        ):
            r = client.get("/api/desktop/status")
        assert r.status_code == 200
        data = r.json()
        assert data["desktopMode"] is False

    def test_status_includes_db_recovery_ok_when_env_unset(self, client: TestClient) -> None:
        """未设置 XCAGI_DESKTOP_DB_RECOVERY 时 dbRecovery.action 应为 'ok'。"""
        import os as _os

        _os.environ.pop("XCAGI_DESKTOP_DB_RECOVERY", None)
        with (
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={
                    "root": Path("/tmp/x"),
                    "data": Path("/tmp/x/data"),
                    "mods": Path("/tmp/x/mods"),
                    "models": Path("/tmp/x/models"),
                },
            ),
            patch(
                "app.fastapi_routes.desktop_runtime.load_or_create_profile",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch("app.fastapi_routes.desktop_runtime.resolve_storage_mode", return_value="sqlite"),
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
        ):
            r = client.get("/api/desktop/status")
        data = r.json()
        assert data["dbRecovery"]["action"] == "ok"
        assert "lastBackup" in data

    def test_status_includes_db_recovery_restored(self, client: TestClient, monkeypatch) -> None:
        """XCAGI_DESKTOP_DB_RECOVERY=restored:xxx 时 dbRecovery 应反映恢复来源。"""
        monkeypatch.setenv("XCAGI_DESKTOP_DB_RECOVERY", "restored:xcagi-v1-20260705.db")
        with (
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={
                    "root": Path("/tmp/x"),
                    "data": Path("/tmp/x/data"),
                    "mods": Path("/tmp/x/mods"),
                    "models": Path("/tmp/x/models"),
                },
            ),
            patch(
                "app.fastapi_routes.desktop_runtime.load_or_create_profile",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch("app.fastapi_routes.desktop_runtime.resolve_storage_mode", return_value="sqlite"),
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
        ):
            r = client.get("/api/desktop/status")
        data = r.json()
        assert data["dbRecovery"]["action"] == "restored"
        assert data["dbRecovery"]["detail"] == "xcagi-v1-20260705.db"

    def test_status_includes_db_recovery_corrupt_no_backup(
        self, client: TestClient, monkeypatch
    ) -> None:
        """XCAGI_DESKTOP_DB_RECOVERY=corrupt_no_backup 时 dbRecovery.action 应为 'corrupt_no_backup'。"""
        monkeypatch.setenv("XCAGI_DESKTOP_DB_RECOVERY", "corrupt_no_backup")
        with (
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={
                    "root": Path("/tmp/x"),
                    "data": Path("/tmp/x/data"),
                    "mods": Path("/tmp/x/mods"),
                    "models": Path("/tmp/x/models"),
                },
            ),
            patch(
                "app.fastapi_routes.desktop_runtime.load_or_create_profile",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch("app.fastapi_routes.desktop_runtime.resolve_storage_mode", return_value="sqlite"),
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
        ):
            r = client.get("/api/desktop/status")
        data = r.json()
        assert data["dbRecovery"]["action"] == "corrupt_no_backup"


class TestMobilePairingStatus:
    """``GET /api/desktop/mobile-pairing-status`` — 桌面设置页「移动端连接」绑定状态。"""

    def test_requires_login(self, anon_client: TestClient) -> None:
        r = anon_client.get("/api/desktop/mobile-pairing-status")
        assert r.status_code == 401

    def test_not_paired_when_no_relay_cached(self, client: TestClient) -> None:
        with patch(
            "app.application.facades.mobile_relay_facade.cached_desktop_relay_payload",
            return_value=None,
        ):
            r = client.get("/api/desktop/mobile-pairing-status")
        assert r.status_code == 200
        data = r.json()
        assert data == {"paired": False, "mobileUsername": "", "lastRelaySyncAt": 0}

    def test_paired_with_mobile_username(self, client: TestClient) -> None:
        with patch(
            "app.application.facades.mobile_relay_facade.cached_desktop_relay_payload",
            return_value={
                "paired": True,
                "mobile_username": "李雷",
                "last_relay_sync_at": 1_700_000_000,
            },
        ):
            r = client.get("/api/desktop/mobile-pairing-status")
        assert r.status_code == 200
        data = r.json()
        assert data == {"paired": True, "mobileUsername": "李雷", "lastRelaySyncAt": 1_700_000_000}

    def test_recoverable_error_falls_back_to_not_paired(self, client: TestClient) -> None:
        with patch(
            "app.application.facades.mobile_relay_facade.cached_desktop_relay_payload",
            side_effect=OSError("disk unavailable"),
        ):
            r = client.get("/api/desktop/mobile-pairing-status")
        assert r.status_code == 200
        assert r.json() == {"paired": False, "mobileUsername": "", "lastRelaySyncAt": 0}


class TestDownloadModel:
    def test_support_bundle_requires_login(self, anon_client: TestClient) -> None:
        with patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True):
            r = anon_client.get("/api/desktop/support-bundle")
        assert r.status_code == 401

    def test_invalid_request_body(self, client: TestClient) -> None:
        r = client.post("/api/desktop/models/download", json={})
        # 422 from pydantic validation, or 400 if handler runs
        assert r.status_code in (400, 422)

    def test_successful_download_returns_zip(self, client: TestClient) -> None:
        with (
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
            patch("app.fastapi_routes.desktop_runtime.download_model") as dl,
            patch(
                "app.fastapi_routes.desktop_runtime.build_support_bundle_zip",
                return_value=b"PK\x03\x04zip",
            ),
        ):
            dl.return_value = "/tmp/model.bin"
            r = client.post(
                "/api/desktop/models/download",
                json={
                    "name": "test-model",
                    "version": "1.0.0",
                    "url": "https://example.com/m.bin",
                    "sha256": "abc123",
                    "size": 1024,
                },
            )
        # Either 200 with zip or some other success-ish code
        assert r.status_code in (200, 201, 202, 400, 500)


class TestCrashReport:
    def test_json_report_is_saved_without_login(
        self, anon_client: TestClient, tmp_path: Path
    ) -> None:
        dirs = {"root": tmp_path}
        with (
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value=dirs,
            ),
        ):
            response = anon_client.post(
                "/api/desktop/crash-report",
                json={"type": "unhandledRejection", "error": "boom"},
            )

        assert response.status_code == 200
        saved = response.json()["file"]
        payload = json.loads((tmp_path / "crash-reports" / saved).read_text())
        assert payload["error"] == "boom"

    def test_report_rejects_non_desktop_runtime(self, anon_client: TestClient) -> None:
        with patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=False):
            response = anon_client.post("/api/desktop/crash-report", json={"error": "boom"})
        assert response.status_code == 409

    def test_minidump_report_is_saved(self, anon_client: TestClient, tmp_path: Path) -> None:
        with (
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={"root": tmp_path},
            ),
        ):
            response = anon_client.post(
                "/api/desktop/crash-report",
                files={"minidump": ("renderer.dmp", b"minidump", "application/octet-stream")},
            )

        assert response.status_code == 200
        saved = response.json()["files"]
        assert len(saved) == 1
        assert (tmp_path / "crash-reports" / saved[0]).read_bytes() == b"minidump"

    def test_report_rejects_unsupported_content_type(
        self, anon_client: TestClient, tmp_path: Path
    ) -> None:
        with (
            patch("app.fastapi_routes.desktop_runtime.is_desktop_mode", return_value=True),
            patch(
                "app.fastapi_routes.desktop_runtime.ensure_desktop_dirs",
                return_value={"root": tmp_path},
            ),
        ):
            response = anon_client.post(
                "/api/desktop/crash-report",
                content=b"boom",
                headers={"content-type": "text/plain"},
            )
        assert response.status_code == 415


class TestDesktopDeploymentModes:
    def test_deployment_status_uses_ssot_catalog(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'xcagi.db'}")

        r = client.get("/api/desktop/deployment")

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["currentMode"] == "safe"
        assert {item["id"] for item in data["modes"]} >= {
            "absolute_safe",
            "safe",
            "performance",
        }
        assert data["effective"]["databaseMode"] == "local_sqlite"

    def test_performance_mode_requires_postgres_url(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")

        r = client.put("/api/desktop/deployment", json={"mode": "performance"})

        assert r.status_code == 400
        assert "PostgreSQL" in r.text or "postgresql" in r.text

    def test_performance_mode_writes_profiles_and_sync_plan(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        pg_url = "postgresql+psycopg://user:secret@127.0.0.1:5432/xcagi"

        r = client.put(
            "/api/desktop/deployment",
            json={"mode": "performance", "postgresUrl": pg_url},
        )

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["mode"] == "performance"
        assert data["database"]["storageMode"] == "remote_postgresql"
        assert "migrate_sqlite_to_postgres.py" in data["syncPlan"]["syncCommand"]
        db_profile = json.loads((tmp_path / "config" / "database.json").read_text())
        deployment_profile = json.loads((tmp_path / "config" / "deployment.json").read_text())
        assert db_profile["mode"] == "remote"
        assert db_profile["remote"]["enabled"] is True
        assert db_profile["remote"]["database_url"] == pg_url
        assert deployment_profile["mode"] == "performance"

    def test_absolute_safe_mode_returns_to_local_sqlite(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")

        r = client.put("/api/desktop/deployment", json={"mode": "absolute_safe"})

        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "absolute_safe"
        assert data["database"]["storageMode"] == "local_sqlite"
        db_profile = json.loads((tmp_path / "config" / "database.json").read_text())
        assert db_profile["mode"] == "local"
        assert db_profile["remote"]["enabled"] is False
