"""Tests for app.application.admin_deploy_push — coverage ramp."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.application.admin_deploy_push import (
    DeployJob,
    DeployStep,
    _build_steps,
    _fhd_root,
    _local_git_sha,
    _local_version,
    _read_local_manifest,
    check_deploy_updates,
    get_deploy_job,
)


# ========================= _fhd_root ====================================


class TestFhdRoot:
    def test_returns_path(self):
        result = _fhd_root()
        assert isinstance(result, Path)
        assert result.is_absolute()


# ========================= _local_git_sha ===============================


class TestLocalGitSha:
    def test_valid_git_repo(self):
        root = _fhd_root()
        result = _local_git_sha(root)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_nonexistent_dir(self, tmp_path):
        result = _local_git_sha(tmp_path / "nonexistent")
        assert result == "local"

    @patch("app.application.admin_deploy_push.subprocess.run")
    def test_git_failure(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="")
        result = _local_git_sha(Path("/tmp"))
        assert result == "local"

    @patch("app.application.admin_deploy_push.subprocess.run")
    def test_git_timeout(self, mock_run):
        mock_run.side_effect = TimeoutError()
        result = _local_git_sha(Path("/tmp"))
        assert result == "local"


# ========================= _local_version ================================


class TestLocalVersion:
    def test_with_pyproject(self):
        root = _fhd_root()
        result = _local_version(root)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_pyproject(self, tmp_path):
        result = _local_version(tmp_path)
        assert result == "10.0.0"

    def test_pyproject_without_version(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\n")
        result = _local_version(tmp_path)
        assert result == "10.0.0"

    def test_pyproject_with_version(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "1.2.3"\n')
        result = _local_version(tmp_path)
        assert result == "1.2.3"


# ========================= _read_local_manifest ==========================


class TestReadLocalManifest:
    def test_no_manifest(self, tmp_path):
        result = _read_local_manifest(tmp_path)
        assert result is None

    def test_valid_manifest(self, tmp_path):
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text(json.dumps({"version": "10.0.0", "git_sha": "abc123"}))
        result = _read_local_manifest(tmp_path)
        assert result is not None
        assert result["version"] == "10.0.0"

    def test_invalid_json(self, tmp_path):
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text("not json")
        result = _read_local_manifest(tmp_path)
        assert result is None

    def test_non_dict_json(self, tmp_path):
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text(json.dumps([1, 2, 3]))
        result = _read_local_manifest(tmp_path)
        assert result is None


# ========================= DeployStep ====================================


class TestDeployStep:
    def test_defaults(self):
        step = DeployStep(id="test", label="Test Step")
        assert step.status == "pending"
        assert step.detail == ""
        assert step.started_at is None
        assert step.finished_at is None

    def test_custom_status(self):
        step = DeployStep(id="test", label="Test", status="running")
        assert step.status == "running"


# ========================= DeployJob =====================================


class TestDeployJob:
    def test_defaults(self):
        job = DeployJob(job_id="j1", options={})
        assert job.status == "queued"
        assert job.steps == []
        assert job.error == ""
        assert job.finished_at is None

    def test_to_dict(self):
        job = DeployJob(
            job_id="j1",
            options={"channel": "stable"},
            status="running",
            steps=[DeployStep(id="s1", label="Step 1", status="done")],
        )
        d = job.to_dict()
        assert d["job_id"] == "j1"
        assert d["status"] == "running"
        assert d["options"] == {"channel": "stable"}
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "s1"
        assert d["steps"][0]["status"] == "done"

    def test_to_dict_with_error(self):
        job = DeployJob(job_id="j1", options={}, status="error", error="something failed")
        d = job.to_dict()
        assert d["error"] == "something failed"


# ========================= _build_steps ==================================


class TestBuildSteps:
    def test_default_steps(self):
        steps = _build_steps({})
        step_ids = [s.id for s in steps]
        assert "check" in step_ids
        assert "pack" in step_ids
        assert "push" in step_ids
        assert "frontend_build" in step_ids
        assert "frontend_push" in step_ids
        assert "verify" in step_ids

    def test_skip_pack(self):
        steps = _build_steps({"skip_pack": True})
        step_ids = [s.id for s in steps]
        assert "pack" not in step_ids
        assert "push" in step_ids

    def test_backend_only(self):
        steps = _build_steps({"include_frontend": False})
        step_ids = [s.id for s in steps]
        assert "frontend_build" not in step_ids
        assert "frontend_push" not in step_ids
        assert "push" in step_ids

    def test_frontend_only(self):
        steps = _build_steps({"include_backend": False})
        step_ids = [s.id for s in steps]
        assert "pack" not in step_ids
        assert "push" not in step_ids
        assert "frontend_build" in step_ids

    def test_no_include(self):
        steps = _build_steps({"include_backend": False, "include_frontend": False})
        step_ids = [s.id for s in steps]
        assert step_ids == ["check", "verify"]


# ========================= get_deploy_job ================================


class TestGetDeployJob:
    def test_nonexistent_job(self):
        from app.application import admin_deploy_push

        original_jobs = admin_deploy_push._JOBS.copy()
        try:
            admin_deploy_push._JOBS.clear()
            result = get_deploy_job("nonexistent")
            assert result is None
        finally:
            admin_deploy_push._JOBS.clear()
            admin_deploy_push._JOBS.update(original_jobs)

    def test_existing_job(self):
        from app.application import admin_deploy_push

        original_jobs = admin_deploy_push._JOBS.copy()
        try:
            admin_deploy_push._JOBS.clear()
            job = DeployJob(job_id="test_j1", options={})
            admin_deploy_push._JOBS["test_j1"] = job
            result = get_deploy_job("test_j1")
            assert result is job
        finally:
            admin_deploy_push._JOBS.clear()
            admin_deploy_push._JOBS.update(original_jobs)


# ========================= check_deploy_updates ==========================


class TestCheckDeployUpdates:
    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    def test_basic_structure(
        self, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_enterprise
    ):
        mock_sha.return_value = "abc123def456"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = {"git_sha": "abc123def456"}
        mock_fetch.return_value = {"git_sha": "abc123def456", "version": "10.0.0", "sha256": "hash123"}
        mock_enterprise.return_value = {"reachable": True, "deploy_sha256": "hash123"}

        result = check_deploy_updates()
        assert "admin_local" in result
        assert "update_hub" in result
        assert "enterprise" in result
        assert "flags" in result

    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    def test_needs_push_when_remote_differs(
        self, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_enterprise
    ):
        mock_sha.return_value = "new_sha_12345"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = None
        mock_fetch.return_value = {"git_sha": "old_sha_67890", "version": "9.0.0", "sha256": "old_hash"}
        mock_enterprise.return_value = {"reachable": True, "deploy_sha256": "old_hash"}

        result = check_deploy_updates()
        assert result["flags"]["needs_push"] is True

    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    def test_up_to_date(self, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_enterprise):
        mock_sha.return_value = "abc123def456"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = {"git_sha": "abc123def456"}
        mock_fetch.return_value = {"git_sha": "abc123def456", "version": "10.0.0", "sha256": "hash123"}
        mock_enterprise.return_value = {"reachable": True, "deploy_sha256": "hash123"}

        result = check_deploy_updates()
        assert result["flags"]["up_to_date"] is True
        assert result["flags"]["needs_push"] is False

    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    def test_local_sha_means_no_push(
        self, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_enterprise
    ):
        mock_sha.return_value = "local"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = None
        mock_fetch.return_value = None
        mock_enterprise.return_value = {"reachable": False}

        result = check_deploy_updates()
        assert result["flags"]["needs_push"] is False

    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    def test_needs_pack_when_manifest_stale(
        self, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_enterprise
    ):
        mock_sha.return_value = "abc123def456"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = {"git_sha": "old_sha"}
        mock_fetch.return_value = {"git_sha": "abc123def456", "version": "10.0.0", "sha256": "hash123"}
        mock_enterprise.return_value = {"reachable": True, "deploy_sha256": "hash123"}

        result = check_deploy_updates()
        assert result["flags"]["needs_pack"] is True

    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    def test_hub_unreachable(
        self, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_enterprise
    ):
        mock_sha.return_value = "abc123def456"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = None
        mock_fetch.return_value = None
        mock_enterprise.return_value = {"reachable": False}

        result = check_deploy_updates()
        assert result["update_hub"]["reachable"] is False
