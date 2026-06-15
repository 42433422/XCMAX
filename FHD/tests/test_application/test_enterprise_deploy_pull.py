"""Tests for app.application.enterprise_deploy_pull — pure helper functions and dataclasses."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.enterprise_deploy_pull import (
    PullJob,
    PullStep,
    _build_pull_steps,
    _read_deployed_sha256,
    _read_local_manifest_file,
    check_enterprise_updates,
    get_pull_job,
)


# ========================= PullStep ======================================


class TestPullStep:
    def test_defaults(self):
        step = PullStep(id="test", label="Test Step")
        assert step.status == "pending"
        assert step.detail == ""
        assert step.started_at is None
        assert step.finished_at is None

    def test_custom(self):
        step = PullStep(id="test", label="Test", status="done", detail="ok")
        assert step.status == "done"
        assert step.detail == "ok"


# ========================= PullJob =======================================


class TestPullJob:
    def test_to_dict(self):
        job = PullJob(
            job_id="abc123",
            options={"force": True},
            steps=[PullStep(id="check", label="Check")],
        )
        d = job.to_dict()
        assert d["job_id"] == "abc123"
        assert d["status"] == "queued"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "check"

    def test_defaults(self):
        job = PullJob(job_id="test", options={})
        assert job.status == "queued"
        assert job.error == ""
        assert job.finished_at is None


# ========================= _build_pull_steps =============================


class TestBuildPullSteps:
    def test_default(self):
        steps = _build_pull_steps({})
        ids = [s.id for s in steps]
        assert "check" in ids
        assert "apply_backend" in ids
        assert "apply_frontend" in ids
        assert "restart" in ids
        assert "verify" in ids

    def test_no_backend(self):
        steps = _build_pull_steps({"include_backend": False})
        ids = [s.id for s in steps]
        assert "apply_backend" not in ids

    def test_no_frontend(self):
        steps = _build_pull_steps({"include_frontend": False})
        ids = [s.id for s in steps]
        assert "apply_frontend" not in ids


# ========================= _read_deployed_sha256 =========================


class TestReadDeployedSha256:
    def test_no_file(self):
        with patch("app.application.enterprise_deploy_pull.DEPLOY_ROOT", "/nonexistent"):
            result = _read_deployed_sha256()
            assert result == ""

    def test_with_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sha_path = Path(tmpdir) / ".deploy-sha256"
            sha_path.write_text("abc123def456")
            with patch("app.application.enterprise_deploy_pull.DEPLOY_ROOT", tmpdir):
                result = _read_deployed_sha256()
                assert result == "abc123def456"


# ========================= _read_local_manifest_file =====================


class TestReadLocalManifestFile:
    def test_no_file(self):
        with patch("app.application.enterprise_deploy_pull.MANIFEST_PATH", "/nonexistent/manifest.json"):
            result = _read_local_manifest_file()
            assert result is None

    def test_valid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"sha256": "abc", "version": "1.0"}, f)
            path = f.name
        try:
            with patch("app.application.enterprise_deploy_pull.MANIFEST_PATH", path):
                result = _read_local_manifest_file()
                assert result is not None
                assert result["sha256"] == "abc"
        finally:
            os.unlink(path)

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            with patch("app.application.enterprise_deploy_pull.MANIFEST_PATH", path):
                result = _read_local_manifest_file()
                assert result is None
        finally:
            os.unlink(path)


# ========================= get_pull_job ==================================


class TestGetPullJob:
    def test_not_found(self):
        result = get_pull_job("nonexistent")
        assert result is None


# ========================= check_enterprise_updates ======================


class TestCheckEnterpriseUpdates:
    def test_structure(self):
        with patch("app.application.enterprise_deploy_pull._fetch_hub_manifest", return_value=None), \
             patch("app.application.enterprise_deploy_pull._read_deployed_sha256", return_value=""):
            result = check_enterprise_updates()
            assert "role" in result
            assert result["role"] == "enterprise"
            assert "update_hub" in result
            assert "enterprise" in result
            assert "flags" in result

    def test_needs_update(self):
        with patch("app.application.enterprise_deploy_pull._fetch_hub_manifest", return_value={"sha256": "newsha"}), \
             patch("app.application.enterprise_deploy_pull._read_deployed_sha256", return_value="oldsha"):
            result = check_enterprise_updates()
            assert result["flags"]["needs_update"] is True

    def test_up_to_date(self):
        with patch("app.application.enterprise_deploy_pull._fetch_hub_manifest", return_value={"sha256": "samesha"}), \
             patch("app.application.enterprise_deploy_pull._read_deployed_sha256", return_value="samesha"):
            result = check_enterprise_updates()
            assert result["flags"]["needs_update"] is False
            assert result["flags"]["up_to_date"] is True

    def test_no_hub_manifest(self):
        with patch("app.application.enterprise_deploy_pull._fetch_hub_manifest", return_value=None), \
             patch("app.application.enterprise_deploy_pull._read_deployed_sha256", return_value=""):
            result = check_enterprise_updates()
            assert result["flags"]["needs_update"] is False
            assert result["update_hub"]["reachable"] is False
