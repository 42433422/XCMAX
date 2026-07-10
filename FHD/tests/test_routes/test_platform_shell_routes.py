"""Tests for app.fastapi_routes.platform_shell_routes — platform shell API routes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.platform_shell_routes import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# platform_shell_capabilities
# ---------------------------------------------------------------------------


class TestPlatformShellCapabilities:
    def test_returns_success(self):
        client = TestClient(_make_app())
        with patch(
            "app.mod_sdk.platform_shell.build_platform_shell_payload",
            return_value={"edition": "standard"},
        ):
            resp = client.get("/api/platform-shell/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "data" in data

    def test_mod_manager_failure_graceful(self):
        client = TestClient(_make_app())
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("no mods"),
            ),
            patch(
                "app.mod_sdk.platform_shell.build_platform_shell_payload",
                return_value={"edition": "standard"},
            ),
        ):
            resp = client.get("/api/platform-shell/capabilities")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# decoupling_progress
# ---------------------------------------------------------------------------


class TestDecouplingProgress:
    def test_returns_success(self):
        client = TestClient(_make_app())
        with patch(
            "app.mod_sdk.decoupling_progress.build_decoupling_progress_payload",
            return_value={"progress": 0.5},
        ):
            resp = client.get("/api/platform-shell/decoupling-progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# deliverable_status
# ---------------------------------------------------------------------------


class TestDeliverableStatus:
    def test_returns_success(self):
        client = TestClient(_make_app())
        with patch(
            "app.mod_sdk.deliverable_status.build_deliverable_status",
            return_value={"ready": True},
        ):
            resp = client.get("/api/platform-shell/deliverable-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_hides_internal_exception(self):
        client = TestClient(_make_app())
        with patch(
            "app.mod_sdk.deliverable_status.build_deliverable_status",
            side_effect=RuntimeError("secret database path"),
        ):
            resp = client.get("/api/platform-shell/deliverable-status")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "交付状态暂时不可用"
        assert "secret database path" not in resp.text


# ---------------------------------------------------------------------------
# industry_baseline
# ---------------------------------------------------------------------------


class TestIndustryBaseline:
    def test_returns_success(self):
        client = TestClient(_make_app())

        async def mock_build(request, industry_id):
            return {"industry": industry_id}

        with patch(
            "app.mod_sdk.industry_baseline.build_industry_baseline_plan_for_request",
            side_effect=mock_build,
        ):
            resp = client.get("/api/platform-shell/industry-baseline?industry_id=制造业")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# onboarding_industries
# ---------------------------------------------------------------------------


class TestOnboardingIndustries:
    def test_returns_success(self):
        client = TestClient(_make_app())

        async def mock_build(request):
            return {"industries": ["制造业", "零售"]}

        with patch(
            "app.mod_sdk.industry_baseline.build_onboarding_industry_catalog_for_request",
            side_effect=mock_build,
        ):
            resp = client.get("/api/platform-shell/onboarding-industries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# employee_planner_status / employee_tools
# ---------------------------------------------------------------------------


class TestEmployeePlannerStatus:
    def test_returns_success(self):
        client = TestClient(_make_app())
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"tools": []},
        ):
            resp = client.get("/api/platform-shell/employee-planner-status")
        assert resp.status_code == 200


class TestEmployeeTools:
    def test_returns_success(self):
        client = TestClient(_make_app())
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"tools": []},
        ):
            resp = client.get("/api/platform-shell/employee-tools")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# workspace_root
# ---------------------------------------------------------------------------


class TestWorkspaceRoot:
    def test_returns_workspace_root(self):
        client = TestClient(_make_app())
        resp = client.get("/api/platform-shell/workspace-root")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "workspace_root" in data["data"]


# ---------------------------------------------------------------------------
# office_sample_cleanup
# ---------------------------------------------------------------------------


class TestOfficeSampleCleanup:
    def test_cleanup_empty_body(self):
        client = TestClient(_make_app())
        resp = client.post("/api/platform-shell/office-sample-cleanup", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["removed"] == []

    def test_cleanup_nonexistent_files(self):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/platform-shell/office-sample-cleanup",
            json={"file_paths": ["uploads/tutorial/nonexistent.xlsx"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


# ---------------------------------------------------------------------------
# office workspace path confinement
# ---------------------------------------------------------------------------


class TestOfficeWorkspacePathConfinement:
    def test_attendance_ignores_client_workspace_root_and_uses_fixed_db(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = tmp_path / "workspace"
        upload = workspace / "uploads" / "nested" / "attendance.xlsx"
        upload.parent.mkdir(parents=True)
        upload.write_bytes(b"placeholder")
        attacker_root = tmp_path / "attacker-controlled-root"
        monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
        monkeypatch.setattr(
            "app.application.attendance_import_app_service._parse_workbook",
            lambda _path: ([], [], "mingxi"),
        )

        response = TestClient(_make_app()).post(
            "/api/platform-shell/office/confirm",
            json={
                "intent": "attendance",
                "file_path": "uploads/nested/attendance.xlsx",
                "workspace_root": str(attacker_root),
            },
        )

        assert response.status_code == 200
        expected_db = workspace / "data" / "mod_dbs" / "taiyangniao-pro.db"
        assert expected_db.is_file()
        assert response.json()["data"]["db_path"] == str(expected_db)
        assert not (attacker_root / "data" / "mod_dbs" / "taiyangniao-pro.db").exists()

    @pytest.mark.parametrize(
        "untrusted",
        [
            "../../outside.xlsx",
            "%252e%252e%252foutside.xlsx",
        ],
    )
    def test_attendance_route_rejects_traversal_and_double_encoding(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        untrusted: str,
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))

        response = TestClient(_make_app()).post(
            "/api/platform-shell/office/confirm",
            json={
                "intent": "attendance",
                "file_path": untrusted,
                "workspace_root": str(tmp_path / "outside"),
            },
        )

        assert response.status_code == 400
        assert not (workspace / "data" / "mod_dbs" / "taiyangniao-pro.db").exists()

    def test_attendance_route_rejects_symlink_escape(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.xlsx"
        outside.write_bytes(b"outside")
        link = workspace / "attendance.xlsx"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")
        monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))

        response = TestClient(_make_app()).post(
            "/api/platform-shell/office/confirm",
            json={"intent": "attendance", "file_path": "attendance.xlsx"},
        )

        assert response.status_code == 400

    def test_workspace_reader_ignores_client_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))

        response = TestClient(_make_app()).post(
            "/api/platform-shell/workspace-read-files",
            json={"workspace_root": str(outside), "file_paths": ["secret.txt"]},
        )

        assert response.status_code == 200
        assert response.json()["data"]["files"] == [
            {"path": "secret.txt", "kind": "text", "error": "file_not_found"}
        ]
