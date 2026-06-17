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
