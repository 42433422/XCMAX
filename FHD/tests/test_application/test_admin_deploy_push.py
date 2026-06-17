"""Tests for app.application.admin_deploy_push — additional coverage ramp."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.admin_deploy_push import (
    DeployJob,
    DeployStep,
    _build_steps,
    _fetch_json_url,
    _fhd_root,
    _hub_remote_dir,
    _local_git_sha,
    _local_version,
    _probe_enterprise_runtime,
    _read_local_manifest,
    check_deploy_updates,
    get_deploy_job,
    start_deploy_push,
)


# ========================= _hub_remote_dir ====================================


class TestHubRemoteDir:
    def test_default_stable(self):
        with patch.dict(os.environ, {"FHD_PUSH_REMOTE_DIR": ""}, clear=False):
            result = _hub_remote_dir("stable")
            assert result == "/var/www/update/releases/stable/server"

    def test_custom_dir(self):
        with patch.dict(os.environ, {"FHD_PUSH_REMOTE_DIR": "/custom/path"}, clear=False):
            result = _hub_remote_dir("staging")
            assert result == "/custom/path"

    def test_staging_channel(self):
        with patch.dict(os.environ, {"FHD_PUSH_REMOTE_DIR": ""}, clear=False):
            result = _hub_remote_dir("staging")
            assert result == "/var/www/update/releases/staging/server"


# ========================= _fetch_json_url ====================================


class TestFetchJsonUrl:
    @patch("app.application.admin_deploy_push.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"key": "value"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _fetch_json_url("http://example.com/manifest.json")
        assert result == {"key": "value"}

    @patch("app.application.admin_deploy_push.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("connection refused")
        result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    @patch("app.application.admin_deploy_push.urllib.request.urlopen")
    def test_invalid_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    @patch("app.application.admin_deploy_push.urllib.request.urlopen")
    def test_non_dict_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([1, 2, 3]).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None


# ========================= _probe_enterprise_runtime ==========================


class TestProbeEnterpriseRuntime:
    @patch("app.application.admin_deploy_push.urllib.request.urlopen")
    def test_reachable(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"version": "10.0.0", "deploy_sha256": "abc123"}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _probe_enterprise_runtime()
        assert result["reachable"] is True
        assert result["version"] == "10.0.0"
        assert result["deploy_sha256"] == "abc123"
        assert "latency_ms" in result

    @patch("app.application.admin_deploy_push.urllib.request.urlopen")
    def test_unreachable(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("timeout")
        result = _probe_enterprise_runtime()
        assert result["reachable"] is False
        assert result["error"] is not None


# ========================= _read_local_manifest ==============================


class TestReadLocalManifest:
    def test_no_manifest_file(self, tmp_path):
        result = _read_local_manifest(tmp_path)
        assert result is None

    def test_valid_manifest(self, tmp_path):
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text(json.dumps({"git_sha": "abc123"}))
        result = _read_local_manifest(tmp_path)
        assert result is not None
        assert result["git_sha"] == "abc123"

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


# ========================= _local_version ====================================


class TestLocalVersion:
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
        pyproject.write_text('version = "9.5.0"\n')
        result = _local_version(tmp_path)
        assert result == "9.5.0"

    def test_pyproject_read_error(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("version = ")
        result = _local_version(tmp_path)
        assert result == "10.0.0"


# ========================= _build_steps ======================================


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

    def test_frontend_only(self):
        steps = _build_steps({"include_backend": False})
        step_ids = [s.id for s in steps]
        assert "pack" not in step_ids
        assert "push" not in step_ids
        assert "frontend_build" in step_ids


# ========================= DeployJob / DeployStep ============================


class TestDeployJobToDict:
    def test_to_dict(self):
        job = DeployJob(
            job_id="test123",
            options={"channel": "stable"},
            steps=[DeployStep(id="check", label="Check")],
        )
        d = job.to_dict()
        assert d["job_id"] == "test123"
        assert d["status"] == "queued"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "check"


# ========================= get_deploy_job ====================================


class TestGetDeployJob:
    def test_not_found(self):
        result = get_deploy_job("nonexistent")
        assert result is None


# ========================= check_deploy_updates ==============================


class TestCheckDeployUpdates:
    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    @patch("app.application.admin_deploy_push._fhd_root")
    def test_full_check(self, mock_root, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_probe):
        mock_root.return_value = Path("/tmp/fhd")
        mock_sha.return_value = "abc123def456"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = {"git_sha": "abc123def456"}
        mock_fetch.return_value = {"git_sha": "abc123def456", "sha256": "sha256abc", "version": "10.0.0"}
        mock_probe.return_value = {"reachable": True, "deploy_sha256": "sha256abc", "version": "10.0.0"}

        result = check_deploy_updates()
        assert result["admin_local"]["git_sha"] == "abc123def456"
        assert result["flags"]["up_to_date"] is True
        assert result["flags"]["needs_push"] is False

    @patch("app.application.admin_deploy_push._probe_enterprise_runtime")
    @patch("app.application.admin_deploy_push._fetch_json_url")
    @patch("app.application.admin_deploy_push._read_local_manifest")
    @patch("app.application.admin_deploy_push._local_version")
    @patch("app.application.admin_deploy_push._local_git_sha")
    @patch("app.application.admin_deploy_push._fhd_root")
    def test_needs_push(self, mock_root, mock_sha, mock_ver, mock_manifest, mock_fetch, mock_probe):
        mock_root.return_value = Path("/tmp/fhd")
        mock_sha.return_value = "newsha123456"
        mock_ver.return_value = "10.0.0"
        mock_manifest.return_value = None
        mock_fetch.return_value = {"git_sha": "oldsha123456", "sha256": "sha256old"}
        mock_probe.return_value = {"reachable": True, "deploy_sha256": "sha256old"}

        result = check_deploy_updates()
        assert result["flags"]["needs_push"] is True
        assert result["flags"]["needs_pack"] is True


# ========================= start_deploy_push =================================


class TestStartDeployPush:
    @patch("app.application.admin_deploy_push.asyncio.create_task")
    @patch("app.application.admin_deploy_push._JOB_LOCK")
    async def test_start_push_creates_job(self, mock_lock, mock_create_task):
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        job = await start_deploy_push({"channel": "staging"})
        assert job.job_id is not None
        assert job.status == "queued"
        assert len(job.steps) > 0

    @patch("app.application.admin_deploy_push.asyncio.create_task")
    @patch("app.application.admin_deploy_push._JOB_LOCK")
    @patch("app.application.admin_deploy_push._ACTIVE_JOB", None)
    async def test_start_push_default_options(self, mock_lock, mock_create_task):
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        job = await start_deploy_push()
        assert job.options["include_backend"] is True
        assert job.options["include_frontend"] is True
        assert job.options["skip_pack"] is False
        assert job.options["channel"] == "stable"
