"""Tests for app.application.enterprise_deploy_pull — coverage ramp."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.enterprise_deploy_pull import (
    PullJob,
    PullStep,
    _build_pull_steps,
    _fetch_hub_manifest,
    _read_deployed_sha256,
    _read_local_manifest_file,
    check_enterprise_updates,
    get_pull_job,
    start_enterprise_pull,
)

# ========================= _read_deployed_sha256 ==============================


class TestReadDeployedSha256:
    def test_no_file(self, tmp_path):
        with patch("app.application.enterprise_deploy_pull.DEPLOY_ROOT", str(tmp_path)):
            result = _read_deployed_sha256()
            assert result == ""

    def test_valid_file(self, tmp_path):
        sha_file = tmp_path / ".deploy-sha256"
        sha_file.write_text("abc123def456")
        with patch("app.application.enterprise_deploy_pull.DEPLOY_ROOT", str(tmp_path)):
            result = _read_deployed_sha256()
            assert result == "abc123def456"

    def test_read_error(self, tmp_path):
        sha_file = tmp_path / ".deploy-sha256"
        sha_file.write_text("abc")
        with patch("app.application.enterprise_deploy_pull.DEPLOY_ROOT", str(tmp_path)):
            with patch("pathlib.Path.read_text", side_effect=OSError("read error")):
                result = _read_deployed_sha256()
                assert result == ""


# ========================= _read_local_manifest_file =========================


class TestReadLocalManifestFile:
    def test_no_file(self, tmp_path):
        with patch(
            "app.application.enterprise_deploy_pull.MANIFEST_PATH", str(tmp_path / "missing.json")
        ):
            result = _read_local_manifest_file()
            assert result is None

    def test_valid_manifest(self, tmp_path):
        manifest = tmp_path / "fhd-manifest.json"
        manifest.write_text(json.dumps({"git_sha": "abc123", "sha256": "sha256abc"}))
        with patch("app.application.enterprise_deploy_pull.MANIFEST_PATH", str(manifest)):
            result = _read_local_manifest_file()
            assert result is not None
            assert result["git_sha"] == "abc123"

    def test_invalid_json(self, tmp_path):
        manifest = tmp_path / "fhd-manifest.json"
        manifest.write_text("not json")
        with patch("app.application.enterprise_deploy_pull.MANIFEST_PATH", str(manifest)):
            result = _read_local_manifest_file()
            assert result is None

    def test_non_dict_json(self, tmp_path):
        manifest = tmp_path / "fhd-manifest.json"
        manifest.write_text(json.dumps([1, 2, 3]))
        with patch("app.application.enterprise_deploy_pull.MANIFEST_PATH", str(manifest)):
            result = _read_local_manifest_file()
            assert result is None


# ========================= _fetch_hub_manifest ===============================


class TestFetchHubManifest:
    def test_local_manifest_found(self, tmp_path):
        manifest = tmp_path / "fhd-manifest.json"
        manifest.write_text(json.dumps({"git_sha": "local123"}))
        with patch(
            "app.application.enterprise_deploy_pull._read_local_manifest_file",
            return_value={"git_sha": "local123"},
        ):
            result = _fetch_hub_manifest()
            assert result is not None
            assert result["git_sha"] == "local123"

    @patch("app.application.enterprise_deploy_pull._read_local_manifest_file", return_value=None)
    @patch("app.application.enterprise_deploy_pull.urllib.request.urlopen")
    def test_remote_manifest_success(self, mock_urlopen, mock_local):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"git_sha": "remote123"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _fetch_hub_manifest()
        assert result is not None
        assert result["git_sha"] == "remote123"

    @patch("app.application.enterprise_deploy_pull._read_local_manifest_file", return_value=None)
    @patch("app.application.enterprise_deploy_pull.urllib.request.urlopen")
    def test_remote_manifest_error(self, mock_urlopen, mock_local):
        mock_urlopen.side_effect = OSError("connection failed")
        result = _fetch_hub_manifest()
        assert result is None


# ========================= check_enterprise_updates ==========================


class TestCheckEnterpriseUpdates:
    @patch("app.application.enterprise_deploy_pull._read_deployed_sha256")
    @patch("app.application.enterprise_deploy_pull._fetch_hub_manifest")
    def test_up_to_date(self, mock_fetch, mock_sha):
        mock_fetch.return_value = {"sha256": "sha256abc", "git_sha": "abc123", "version": "10.0.0"}
        mock_sha.return_value = "sha256abc"
        result = check_enterprise_updates()
        assert result["flags"]["up_to_date"] is True
        assert result["flags"]["needs_update"] is False

    @patch("app.application.enterprise_deploy_pull._read_deployed_sha256")
    @patch("app.application.enterprise_deploy_pull._fetch_hub_manifest")
    def test_needs_update(self, mock_fetch, mock_sha):
        mock_fetch.return_value = {"sha256": "sha256new", "git_sha": "new123", "version": "10.0.0"}
        mock_sha.return_value = "sha256old"
        result = check_enterprise_updates()
        assert result["flags"]["needs_update"] is True

    @patch("app.application.enterprise_deploy_pull._read_deployed_sha256")
    @patch("app.application.enterprise_deploy_pull._fetch_hub_manifest")
    def test_no_deployed_sha(self, mock_fetch, mock_sha):
        mock_fetch.return_value = {"sha256": "sha256abc", "git_sha": "abc123"}
        mock_sha.return_value = ""
        result = check_enterprise_updates()
        assert result["flags"]["needs_update"] is True

    @patch("app.application.enterprise_deploy_pull._read_deployed_sha256")
    @patch("app.application.enterprise_deploy_pull._fetch_hub_manifest")
    def test_hub_unreachable(self, mock_fetch, mock_sha):
        mock_fetch.return_value = None
        mock_sha.return_value = "sha256abc"
        result = check_enterprise_updates()
        assert result["update_hub"]["reachable"] is False
        assert result["flags"]["needs_update"] is False


# ========================= _build_pull_steps =================================


class TestBuildPullSteps:
    def test_default_steps(self):
        steps = _build_pull_steps({})
        step_ids = [s.id for s in steps]
        assert "check" in step_ids
        assert "apply_backend" in step_ids
        assert "apply_frontend" in step_ids
        assert "restart" in step_ids
        assert "verify" in step_ids

    def test_backend_only(self):
        steps = _build_pull_steps({"include_backend": True, "include_frontend": False})
        step_ids = [s.id for s in steps]
        assert "apply_backend" in step_ids
        assert "apply_frontend" not in step_ids

    def test_frontend_only(self):
        steps = _build_pull_steps({"include_backend": False, "include_frontend": True})
        step_ids = [s.id for s in steps]
        assert "apply_backend" not in step_ids
        assert "apply_frontend" in step_ids


# ========================= PullJob / PullStep ================================


class TestPullJobToDict:
    def test_to_dict(self):
        job = PullJob(
            job_id="test456",
            options={"force": False},
            steps=[PullStep(id="check", label="Check")],
        )
        d = job.to_dict()
        assert d["job_id"] == "test456"
        assert d["status"] == "queued"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "check"


# ========================= get_pull_job ======================================


class TestGetPullJob:
    def test_not_found(self):
        result = get_pull_job("nonexistent")
        assert result is None


# ========================= start_enterprise_pull =============================


class TestStartEnterprisePull:
    @patch("app.application.enterprise_deploy_pull.asyncio.create_task")
    @patch("app.application.enterprise_deploy_pull._PULL_LOCK")
    async def test_start_pull_creates_job(self, mock_lock, mock_create_task):
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        job = await start_enterprise_pull({"force": True})
        assert job.job_id is not None
        assert job.status == "queued"
        assert len(job.steps) > 0

    @patch("app.application.enterprise_deploy_pull.asyncio.create_task")
    @patch("app.application.enterprise_deploy_pull._PULL_LOCK")
    async def test_start_pull_default_options(self, mock_lock, mock_create_task):
        mock_lock.__aenter__ = AsyncMock(return_value=None)
        mock_lock.__aexit__ = AsyncMock(return_value=False)

        job = await start_enterprise_pull()
        assert job.options["include_backend"] is True
        assert job.options["include_frontend"] is True
        assert job.options["force"] is False
