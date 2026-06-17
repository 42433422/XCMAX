"""Extended tests for ``app.application.admin_deploy_push`` covering low-coverage branches."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application import admin_deploy_push as adp
from app.application.admin_deploy_push import (
    DeployJob,
    DeployStep,
    _build_steps,
    _execute_deploy_job,
    _fetch_json_url,
    _fhd_root,
    _hub_remote_dir,
    _local_git_sha,
    _local_version,
    _probe_enterprise_runtime,
    _read_local_manifest,
    _run_shell_step,
    check_deploy_updates,
    get_deploy_job,
    start_deploy_push,
)


class TestLocalGitShaExtended:
    def test_git_sha_success(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="abc123def456\n", returncode=0
            )
            result = _local_git_sha(tmp_path)
        assert result == "abc123def456"

    def test_git_sha_failure_returns_local(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=1)
            result = _local_git_sha(tmp_path)
        assert result == "local"

    def test_git_sha_empty_returns_local(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = _local_git_sha(tmp_path)
        assert result == "local"

    def test_git_sha_oserror_returns_local(self, tmp_path: Path) -> None:
        with patch(
            "subprocess.run", side_effect=OSError("git not found")
        ):
            result = _local_git_sha(tmp_path)
        assert result == "local"

    def test_git_sha_timeout_returns_local(self, tmp_path: Path) -> None:
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=8)
        ):
            result = _local_git_sha(tmp_path)
        assert result == "local"


class TestLocalVersionExtended:
    def test_no_pyproject_returns_default(self, tmp_path: Path) -> None:
        result = _local_version(tmp_path)
        assert result == "10.0.0"

    def test_pyproject_with_version(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "9.5.0"\n')
        result = _local_version(tmp_path)
        assert result == "9.5.0"

    def test_pyproject_without_version_returns_default(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\n")
        result = _local_version(tmp_path)
        assert result == "10.0.0"

    def test_pyproject_read_error_returns_default(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("version = ")
        result = _local_version(tmp_path)
        assert result == "10.0.0"


class TestReadLocalManifestExtended:
    def test_no_file_returns_none(self, tmp_path: Path) -> None:
        result = _read_local_manifest(tmp_path)
        assert result is None

    def test_valid_manifest(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text(json.dumps({"git_sha": "abc123"}))
        result = _read_local_manifest(tmp_path)
        assert result == {"git_sha": "abc123"}

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text("not json")
        result = _read_local_manifest(tmp_path)
        assert result is None

    def test_non_dict_json_returns_none(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text(json.dumps([1, 2, 3]))
        result = _read_local_manifest(tmp_path)
        assert result is None


class TestFetchJsonUrlExtended:
    def test_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"key": "value"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result == {"key": "value"}

    def test_network_error_returns_none(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    def test_invalid_json_returns_none(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    def test_non_dict_json_returns_none(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([1, 2, 3]).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    def test_url_error_returns_none(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=urllib.error.URLError("fail"),
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None


class TestProbeEnterpriseRuntimeExtended:
    def test_reachable(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"version": "10.0.0", "deploy_sha256": "abc123"}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is True
        assert result["version"] == "10.0.0"
        assert result["deploy_sha256"] == "abc123"
        assert "latency_ms" in result

    def test_unreachable(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=OSError("timeout"),
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is False
        assert "error" in result

    def test_invalid_json_returns_unreachable(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is False


class TestCheckDeployUpdatesExtended:
    def test_full_check_up_to_date(self) -> None:
        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp/fhd")
        ), patch(
            "app.application.admin_deploy_push._local_git_sha", return_value="abc123def456"
        ), patch(
            "app.application.admin_deploy_push._local_version", return_value="10.0.0"
        ), patch(
            "app.application.admin_deploy_push._read_local_manifest",
            return_value={"git_sha": "abc123def456"},
        ), patch(
            "app.application.admin_deploy_push._fetch_json_url",
            return_value={
                "git_sha": "abc123def456",
                "sha256": "sha256abc",
                "version": "10.0.0",
            },
        ), patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={
                "reachable": True,
                "deploy_sha256": "sha256abc",
                "version": "10.0.0",
            },
        ):
            result = check_deploy_updates()
        assert result["admin_local"]["git_sha"] == "abc123def456"
        assert result["flags"]["up_to_date"] is True
        assert result["flags"]["needs_push"] is False

    def test_needs_push(self) -> None:
        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp/fhd")
        ), patch(
            "app.application.admin_deploy_push._local_git_sha", return_value="newsha123456"
        ), patch(
            "app.application.admin_deploy_push._local_version", return_value="10.0.0"
        ), patch(
            "app.application.admin_deploy_push._read_local_manifest", return_value=None
        ), patch(
            "app.application.admin_deploy_push._fetch_json_url",
            return_value={"git_sha": "oldsha123456", "sha256": "sha256old"},
        ), patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={"reachable": True, "deploy_sha256": "sha256old"},
        ):
            result = check_deploy_updates()
        assert result["flags"]["needs_push"] is True
        assert result["flags"]["needs_pack"] is True

    def test_local_sha_local_no_push(self) -> None:
        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp/fhd")
        ), patch(
            "app.application.admin_deploy_push._local_git_sha", return_value="local"
        ), patch(
            "app.application.admin_deploy_push._local_version", return_value="10.0.0"
        ), patch(
            "app.application.admin_deploy_push._read_local_manifest", return_value=None
        ), patch(
            "app.application.admin_deploy_push._fetch_json_url",
            return_value={"git_sha": "abc123", "sha256": "sha256abc"},
        ), patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={"reachable": True, "deploy_sha256": "sha256abc"},
        ):
            result = check_deploy_updates()
        assert result["flags"]["needs_push"] is False
        assert result["flags"]["needs_pack"] is False

    def test_hub_no_sha_triggers_push(self) -> None:
        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp/fhd")
        ), patch(
            "app.application.admin_deploy_push._local_git_sha", return_value="abc123def456"
        ), patch(
            "app.application.admin_deploy_push._local_version", return_value="10.0.0"
        ), patch(
            "app.application.admin_deploy_push._read_local_manifest", return_value=None
        ), patch(
            "app.application.admin_deploy_push._fetch_json_url",
            return_value={"git_sha": "", "sha256": ""},
        ), patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={"reachable": True, "deploy_sha256": ""},
        ):
            result = check_deploy_updates()
        assert result["flags"]["needs_push"] is True

    def test_enterprise_pending(self) -> None:
        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp/fhd")
        ), patch(
            "app.application.admin_deploy_push._local_git_sha", return_value="abc123def456"
        ), patch(
            "app.application.admin_deploy_push._local_version", return_value="10.0.0"
        ), patch(
            "app.application.admin_deploy_push._read_local_manifest",
            return_value={"git_sha": "abc123def456"},
        ), patch(
            "app.application.admin_deploy_push._fetch_json_url",
            return_value={
                "git_sha": "abc123def456",
                "sha256": "newsha256",
                "version": "10.0.0",
            },
        ), patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={
                "reachable": True,
                "deploy_sha256": "oldsha256",
                "version": "10.0.0",
            },
        ):
            result = check_deploy_updates()
        assert result["flags"]["enterprise_pending"] is True

    def test_staging_channel(self) -> None:
        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp/fhd")
        ), patch(
            "app.application.admin_deploy_push._local_git_sha", return_value="abc123def456"
        ), patch(
            "app.application.admin_deploy_push._local_version", return_value="10.0.0"
        ), patch(
            "app.application.admin_deploy_push._read_local_manifest", return_value=None
        ), patch(
            "app.application.admin_deploy_push._fetch_json_url", return_value=None
        ), patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={"reachable": False},
        ):
            result = check_deploy_updates(channel="staging")
        assert "staging" in result["update_hub"]["manifest_url"]


class TestBuildStepsExtended:
    def test_default_steps(self) -> None:
        steps = _build_steps({})
        step_ids = [s.id for s in steps]
        assert "check" in step_ids
        assert "pack" in step_ids
        assert "push" in step_ids
        assert "frontend_build" in step_ids
        assert "frontend_push" in step_ids
        assert "verify" in step_ids

    def test_skip_pack(self) -> None:
        steps = _build_steps({"skip_pack": True})
        step_ids = [s.id for s in steps]
        assert "pack" not in step_ids
        assert "push" in step_ids

    def test_backend_only(self) -> None:
        steps = _build_steps({"include_frontend": False})
        step_ids = [s.id for s in steps]
        assert "frontend_build" not in step_ids
        assert "frontend_push" not in step_ids

    def test_frontend_only(self) -> None:
        steps = _build_steps({"include_backend": False})
        step_ids = [s.id for s in steps]
        assert "pack" not in step_ids
        assert "push" not in step_ids
        assert "frontend_build" in step_ids

    def test_no_backend_no_frontend(self) -> None:
        steps = _build_steps({"include_backend": False, "include_frontend": False})
        step_ids = [s.id for s in steps]
        assert "pack" not in step_ids
        assert "push" not in step_ids
        assert "frontend_build" not in step_ids
        assert "verify" in step_ids


class TestDeployJobToDictExtended:
    def test_to_dict(self) -> None:
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
        assert d["steps"][0]["label"] == "Check"

    def test_to_dict_with_error(self) -> None:
        job = DeployJob(
            job_id="err123",
            options={},
            status="error",
            error="something failed",
        )
        d = job.to_dict()
        assert d["status"] == "error"
        assert d["error"] == "something failed"


class TestRunShellStepExtended:
    async def test_run_shell_step_success(self) -> None:
        job = DeployJob(job_id="j1", options={})
        step = DeployStep(id="test", label="Test")
        # Mock subprocess
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        # Simulate one line then EOF
        read_lines = [b"output line\n", b""]

        async def readline():
            return read_lines.pop(0)

        mock_proc.stdout.readline = readline

        async def wait():
            return 0

        mock_proc.wait = wait

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)
        ):
            await _run_shell_step(job, step, ["echo", "hello"], cwd=Path("/tmp"))
        assert step.status == "done"
        assert step.detail == "output line"

    async def test_run_shell_step_failure(self) -> None:
        job = DeployJob(job_id="j2", options={})
        step = DeployStep(id="test", label="Test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()

        async def readline():
            return b""

        mock_proc.stdout.readline = readline

        async def wait():
            return 1

        mock_proc.wait = wait

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)
        ):
            with pytest.raises(RuntimeError):
                await _run_shell_step(job, step, ["false"], cwd=Path("/tmp"))
        assert step.status == "error"

    async def test_run_shell_step_oserror(self) -> None:
        job = DeployJob(job_id="j3", options={})
        step = DeployStep(id="test", label="Test")
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError("spawn fail")),
        ):
            with pytest.raises(OSError):
                await _run_shell_step(job, step, ["cmd"], cwd=Path("/tmp"))
        assert step.status == "error"


class TestExecuteDeployJobExtended:
    async def test_execute_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Reset state
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": True,
            "include_frontend": True,
            "skip_pack": False,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec1",
            options=opts,
            steps=_build_steps(opts),
        )

        async def fake_run_step(job, step, cmd, *, cwd=None, env=None):
            step.status = "done"
            step.started_at = time.time()
            step.finished_at = time.time()

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": "abc123"},
                "update_hub": {"git_sha": "abc123"},
            },
        ), patch(
            "app.application.admin_deploy_push._run_shell_step",
            new=AsyncMock(side_effect=fake_run_step),
        ):
            await _execute_deploy_job(job)
        assert job.status == "done"

    async def test_execute_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": True,
            "include_frontend": False,
            "skip_pack": False,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec2",
            options=opts,
            steps=_build_steps(opts),
        )

        call_count = {"n": 0}

        async def fake_run_step(job, step, cmd, *, cwd=None, env=None):
            call_count["n"] += 1
            step.status = "running"
            step.started_at = time.time()
            if call_count["n"] == 1:  # pack step fails
                step.status = "error"
                step.finished_at = time.time()
                raise RuntimeError("pack failed")
            step.status = "done"
            step.finished_at = time.time()

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": "abc123"},
                "update_hub": {"git_sha": "abc123"},
            },
        ), patch(
            "app.application.admin_deploy_push._run_shell_step",
            new=AsyncMock(side_effect=fake_run_step),
        ):
            await _execute_deploy_job(job)
        assert job.status == "error"
        assert "pack failed" in job.error

    async def test_execute_skip_pack(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": True,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec3",
            options=opts,
            steps=_build_steps(opts),
        )

        async def fake_run_step(job, step, cmd, *, cwd=None, env=None):
            step.status = "done"
            step.started_at = time.time()
            step.finished_at = time.time()

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": "abc123"},
                "update_hub": {"git_sha": "abc123"},
            },
        ), patch(
            "app.application.admin_deploy_push._run_shell_step",
            new=AsyncMock(side_effect=fake_run_step),
        ):
            await _execute_deploy_job(job)
        assert job.status == "done"

    async def test_execute_verify_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": False,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec4",
            options=opts,
            steps=_build_steps(opts),
        )

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": "localsha12345"},
                "update_hub": {"git_sha": "different_sha"},
            },
        ), patch("asyncio.sleep", new=AsyncMock()):
            await _execute_deploy_job(job)
        # Verify step should fail with mismatch
        assert job.status == "error"


class TestStartDeployPushExtended:
    async def test_start_push_creates_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        with patch("asyncio.create_task", new=Mock()):
            job = await start_deploy_push({"channel": "staging"})
        assert job.job_id is not None
        assert job.status == "queued"
        assert len(job.steps) > 0
        assert job.options["channel"] == "staging"

    async def test_start_push_default_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        with patch("asyncio.create_task", new=Mock()):
            job = await start_deploy_push()
        assert job.options["include_backend"] is True
        assert job.options["include_frontend"] is True
        assert job.options["skip_pack"] is False
        assert job.options["channel"] == "stable"

    async def test_start_push_with_active_job_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Set up an active running job
        active_job = DeployJob(job_id="active", options={}, status="running")
        monkeypatch.setattr(adp, "_ACTIVE_JOB", "active")
        monkeypatch.setattr(adp, "_JOBS", {"active": active_job})

        with pytest.raises(RuntimeError, match="已有推送任务进行中"):
            await start_deploy_push()

    async def test_start_push_with_completed_active_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Active job exists but is done - should allow new job
        active_job = DeployJob(job_id="active", options={}, status="done")
        monkeypatch.setattr(adp, "_ACTIVE_JOB", "active")
        monkeypatch.setattr(adp, "_JOBS", {"active": active_job})

        with patch("asyncio.create_task", new=Mock()):
            job = await start_deploy_push()
        assert job.job_id != "active"


class TestGetDeployJobExtended:
    def test_not_found(self) -> None:
        result = get_deploy_job("nonexistent")
        assert result is None

    def test_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        job = DeployJob(job_id="found", options={})
        monkeypatch.setattr(adp, "_JOBS", {"found": job})
        result = get_deploy_job("found")
        assert result is job


class TestHubRemoteDirExtended:
    def test_default_stable(self) -> None:
        with patch.dict(os.environ, {"FHD_PUSH_REMOTE_DIR": ""}, clear=False):
            result = _hub_remote_dir("stable")
            assert result == "/var/www/update/releases/stable/server"

    def test_custom_dir(self) -> None:
        with patch.dict(
            os.environ, {"FHD_PUSH_REMOTE_DIR": "/custom/path"}, clear=False
        ):
            result = _hub_remote_dir("staging")
            assert result == "/custom/path"

    def test_staging_channel(self) -> None:
        with patch.dict(os.environ, {"FHD_PUSH_REMOTE_DIR": ""}, clear=False):
            result = _hub_remote_dir("staging")
            assert result == "/var/www/update/releases/staging/server"
