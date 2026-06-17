"""Deep tests for ``app.application.admin_deploy_push`` covering remaining uncovered branches."""
from __future__ import annotations

import asyncio
import json
import os
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


# ── _local_git_sha deep ──────────────────────────────────────────────────────


class TestLocalGitShaDeep:
    def test_subprocess_timeout_returns_local(self, tmp_path: Path) -> None:
        import subprocess

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=8),
        ):
            result = _local_git_sha(tmp_path)
        assert result == "local"

    def test_returncode_nonzero_with_stdout_returns_local(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="someoutput\n", returncode=1)
            result = _local_git_sha(tmp_path)
        assert result == "local"

    def test_json_decode_error_returns_local(self, tmp_path: Path) -> None:
        # json.JSONDecodeError is in _DEPLOY_ERRORS but subprocess.run doesn't raise it
        # This tests the except clause path with a different error type
        with patch(
            "subprocess.run",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _local_git_sha(tmp_path)
        assert result == "local"


# ── _local_version deep ──────────────────────────────────────────────────────


class TestLocalVersionDeep:
    def test_pyproject_with_multiline_version(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "10.5.2"\n')
        result = _local_version(tmp_path)
        assert result == "10.5.2"

    def test_pyproject_read_oserror_returns_default(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "9.0.0"\n')
        with patch(
            "pathlib.Path.read_text",
            side_effect=OSError("permission denied"),
        ):
            result = _local_version(tmp_path)
        assert result == "10.0.0"


# ── _read_local_manifest deep ────────────────────────────────────────────────


class TestReadLocalManifestDeep:
    def test_read_oserror_returns_none(self, tmp_path: Path) -> None:
        dist_dir = tmp_path / "dist" / "deploy"
        dist_dir.mkdir(parents=True)
        manifest = dist_dir / "fhd-manifest.json"
        manifest.write_text(json.dumps({"key": "val"}))
        with patch(
            "pathlib.Path.read_text",
            side_effect=OSError("permission denied"),
        ):
            result = _read_local_manifest(tmp_path)
        assert result is None


# ── _fetch_json_url deep ─────────────────────────────────────────────────────


class TestFetchJsonUrlDeep:
    def test_timeout_error_returns_none(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    def test_runtime_error_returns_none(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        assert result is None

    def test_empty_body_returns_none(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _fetch_json_url("http://example.com/manifest.json")
        # Empty body → json.loads("") raises JSONDecodeError → returns None
        assert result is None

    def test_custom_timeout(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"a": 1}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ) as mock_urlopen:
            _fetch_json_url("http://example.com/manifest.json", timeout=15.0)
        # Verify timeout was passed
        assert mock_urlopen.call_args[1]["timeout"] == 15.0


# ── _probe_enterprise_runtime deep ───────────────────────────────────────────


class TestProbeEnterpriseRuntimeDeep:
    def test_runtime_error_returns_unreachable(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is False
        assert "error" in result

    def test_timeout_returns_unreachable(self) -> None:
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is False

    def test_non_dict_body_returns_unreachable(self) -> None:
        mock_resp = MagicMock()
        # Invalid JSON triggers JSONDecodeError which is in _DEPLOY_ERRORS
        mock_resp.read.return_value = b"not valid json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is False

    def test_reachable_with_empty_body_fields(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch(
            "app.application.admin_deploy_push.urllib.request.urlopen",
            return_value=mock_resp,
        ):
            result = _probe_enterprise_runtime()
        assert result["reachable"] is True
        assert result["version"] == ""
        assert result["deploy_sha256"] == ""


# ── check_deploy_updates deep ────────────────────────────────────────────────


class TestCheckDeployUpdatesDeep:
    def test_staging_channel_replaces_url(self) -> None:
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
        ) as mock_fetch, patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={"reachable": False, "deploy_sha256": ""},
        ):
            result = check_deploy_updates(channel="staging")
        # Verify the manifest URL was modified for staging
        called_url = mock_fetch.call_args[0][0]
        assert "/staging/" in called_url
        assert "/stable/" not in called_url

    def test_stable_channel_uses_default_url(self) -> None:
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
        ) as mock_fetch, patch(
            "app.application.admin_deploy_push._probe_enterprise_runtime",
            return_value={"reachable": False, "deploy_sha256": ""},
        ):
            result = check_deploy_updates(channel="stable")
        called_url = mock_fetch.call_args[0][0]
        assert "/stable/" in called_url

    def test_hub_sha_empty_with_local_sha_triggers_push(self) -> None:
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
            return_value={"reachable": False, "deploy_sha256": ""},
        ):
            result = check_deploy_updates()
        assert result["flags"]["needs_push"] is True

    def test_enterprise_pending_with_hub_tar_sha(self) -> None:
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
                "built_at": "2026-01-01T00:00:00Z",
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
        assert result["update_hub"]["built_at"] == "2026-01-01T00:00:00Z"

    def test_up_to_date_with_matching_shas(self) -> None:
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
            },
        ):
            result = check_deploy_updates()
        assert result["flags"]["up_to_date"] is True
        assert result["flags"]["enterprise_pending"] is False


# ── _run_shell_step deep ─────────────────────────────────────────────────────


class TestRunShellStepDeep:
    async def test_run_shell_step_multiple_lines_tail(self) -> None:
        """Test that tail list is managed correctly with many output lines."""
        job = DeployJob(job_id="j1", options={})
        step = DeployStep(id="test", label="Test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        # Simulate 10 lines then EOF - tests the tail.pop(0) branch
        read_lines = [f"line {i}\n".encode() for i in range(10)] + [b""]

        async def readline():
            return read_lines.pop(0)

        mock_proc.stdout.readline = readline

        async def wait():
            return 0

        mock_proc.wait = wait

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)
        ):
            await _run_shell_step(job, step, ["echo", "many"], cwd=Path("/tmp"))
        assert step.status == "done"
        # tail[-1] should be the last line
        assert step.detail == "line 9"

    async def test_run_shell_step_empty_output(self) -> None:
        """Test step with no output lines - detail should be 'exit {code}'."""
        job = DeployJob(job_id="j2", options={})
        step = DeployStep(id="test", label="Test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()

        async def readline():
            return b""

        mock_proc.stdout.readline = readline

        async def wait():
            return 0

        mock_proc.wait = wait

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)
        ):
            await _run_shell_step(job, step, ["true"], cwd=Path("/tmp"))
        assert step.status == "done"
        assert step.detail == "exit 0"

    async def test_run_shell_step_with_env(self) -> None:
        """Test that custom env is merged with os.environ."""
        job = DeployJob(job_id="j3", options={})
        step = DeployStep(id="test", label="Test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()

        async def readline():
            return b""

        mock_proc.stdout.readline = readline

        async def wait():
            return 0

        mock_proc.wait = wait

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)
        ) as mock_exec:
            await _run_shell_step(
                job,
                step,
                ["echo", "hello"],
                cwd=Path("/tmp"),
                env={"CUSTOM_VAR": "value"},
            )
        # Verify env was passed and merged
        passed_env = mock_exec.call_args[1]["env"]
        assert passed_env["CUSTOM_VAR"] == "value"
        # Should also contain PATH from os.environ
        assert "PATH" in passed_env

    async def test_run_shell_step_detail_truncation(self) -> None:
        """Test that long detail is truncated to 500 chars on error."""
        job = DeployJob(job_id="j4", options={})
        step = DeployStep(id="test", label="Test")
        long_error = "x" * 1000
        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError(long_error)),
        ):
            with pytest.raises(OSError):
                await _run_shell_step(job, step, ["cmd"], cwd=Path("/tmp"))
        assert step.status == "error"
        assert len(step.detail) == 500

    async def test_run_shell_step_finally_sets_finished_at(self) -> None:
        """Test that finished_at is always set in finally block."""
        job = DeployJob(job_id="j5", options={})
        step = DeployStep(id="test", label="Test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        # Return one line then EOF to avoid infinite loop
        read_lines = [b"output\n", b""]

        async def readline():
            return read_lines.pop(0)

        mock_proc.stdout.readline = readline

        async def wait():
            return 0

        mock_proc.wait = wait

        assert step.finished_at is None
        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)
        ):
            await _run_shell_step(job, step, ["echo"], cwd=Path("/tmp"))
        assert step.finished_at is not None


# ── _execute_deploy_job deep ─────────────────────────────────────────────────


class TestExecuteDeployJobDeep:
    async def test_execute_with_frontend_steps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that frontend_build and frontend_push steps are executed."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": False,
            "include_frontend": True,
            "skip_pack": False,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec_fe",
            options=opts,
            steps=_build_steps(opts),
        )

        executed_steps: list[str] = []

        async def fake_run_step(job, step, cmd, *, cwd=None, env=None):
            executed_steps.append(step.id)
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
        assert "frontend_build" in executed_steps
        assert "frontend_push" in executed_steps

    async def test_execute_verify_step_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test verify step when hub_sha matches local_sha."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": False,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec_verify",
            options=opts,
            steps=_build_steps(opts),
        )

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": "matchingsha1"},
                "update_hub": {"git_sha": "matchingsha1"},
            },
        ), patch("asyncio.sleep", new=AsyncMock()):
            await _execute_deploy_job(job)
        assert job.status == "done"
        # Find the verify step
        verify_step = next(s for s in job.steps if s.id == "verify")
        assert verify_step.status == "done"

    async def test_execute_verify_step_empty_local_sha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test verify step when local_sha is empty - should not error."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": False,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec_empty",
            options=opts,
            steps=_build_steps(opts),
        )

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": ""},
                "update_hub": {"git_sha": "different"},
            },
        ), patch("asyncio.sleep", new=AsyncMock()):
            await _execute_deploy_job(job)
        # Empty local_sha → not error (condition: hub_sha == local_sha or not local_sha)
        assert job.status == "done"

    async def test_execute_sets_ssh_key_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that ssh_key option is set in deploy env."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": True,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
            "ssh_key": "my_ssh_key_value",
        }
        job = DeployJob(
            job_id="exec_ssh",
            options=opts,
            steps=_build_steps(opts),
        )

        captured_envs: list[dict] = []

        async def fake_run_step(job, step, cmd, *, cwd=None, env=None):
            if env:
                captured_envs.append(env)
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
        # At least one env should contain the ssh key
        assert any(e.get("FHD_PUSH_SSH_KEY") == "my_ssh_key_value" for e in captured_envs)

    async def test_execute_clears_active_job_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that _ACTIVE_JOB is cleared in finally block."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", "test_job_id")
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": False,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="test_job_id",
            options=opts,
            steps=_build_steps(opts),
        )

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            return_value={
                "admin_local": {"git_sha": "abc123"},
                "update_hub": {"git_sha": "abc123"},
            },
        ), patch("asyncio.sleep", new=AsyncMock()):
            await _execute_deploy_job(job)
        assert adp._ACTIVE_JOB is None

    async def test_execute_clears_active_job_on_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that _ACTIVE_JOB is cleared even on error."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", "test_job_err")
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": False,
            "include_frontend": False,
            "skip_pack": True,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="test_job_err",
            options=opts,
            steps=_build_steps(opts),
        )

        with patch(
            "app.application.admin_deploy_push._fhd_root", return_value=Path("/tmp")
        ), patch(
            "app.application.admin_deploy_push.check_deploy_updates",
            side_effect=RuntimeError("check failed"),
        ), patch("asyncio.sleep", new=AsyncMock()):
            await _execute_deploy_job(job)
        assert job.status == "error"
        assert adp._ACTIVE_JOB is None

    async def test_execute_running_steps_marked_error_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that running steps are marked as error when job fails."""
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        opts = {
            "include_backend": True,
            "include_frontend": True,
            "skip_pack": False,
            "channel": "stable",
        }
        job = DeployJob(
            job_id="exec_running_err",
            options=opts,
            steps=_build_steps(opts),
        )

        call_count = {"n": 0}

        async def fake_run_step(job, step, cmd, *, cwd=None, env=None):
            call_count["n"] += 1
            step.status = "running"
            step.started_at = time.time()
            if call_count["n"] == 1:  # pack step fails
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
        # The pack step should be error
        pack_step = next((s for s in job.steps if s.id == "pack"), None)
        if pack_step:
            assert pack_step.status == "error"


# ── start_deploy_push deep ───────────────────────────────────────────────────


class TestStartDeployPushDeep:
    async def test_start_push_generates_unique_job_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        with patch("asyncio.create_task", new=Mock()):
            job1 = await start_deploy_push({"channel": "stable"})
            job2 = await start_deploy_push({"channel": "stable"})
        assert job1.job_id != job2.job_id

    async def test_start_push_stores_job_in_jobs_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})

        with patch("asyncio.create_task", new=Mock()):
            job = await start_deploy_push({"channel": "staging"})
        assert adp._JOBS[job.job_id] is job
        assert adp._ACTIVE_JOB == job.job_id

    async def test_start_push_with_ssh_key_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(adp, "_ACTIVE_JOB", None)
        monkeypatch.setattr(adp, "_JOBS", {})
        monkeypatch.setenv("FHD_PUSH_SSH_KEY", "env_ssh_key")

        with patch("asyncio.create_task", new=Mock()):
            job = await start_deploy_push()
        # The ssh_key is read in _execute_deploy_job, not start_deploy_push
        # But we can verify the job was created
        assert job.status == "queued"


# ── DeployJob.to_dict deep ───────────────────────────────────────────────────


class TestDeployJobToDictDeep:
    def test_to_dict_with_multiple_steps(self) -> None:
        steps = [
            DeployStep(id="check", label="Check", status="done"),
            DeployStep(id="pack", label="Pack", status="error", detail="failed"),
            DeployStep(id="push", label="Push", status="pending"),
        ]
        job = DeployJob(
            job_id="multi",
            options={"channel": "stable"},
            steps=steps,
        )
        d = job.to_dict()
        assert len(d["steps"]) == 3
        assert d["steps"][0]["status"] == "done"
        assert d["steps"][1]["status"] == "error"
        assert d["steps"][1]["detail"] == "failed"
        assert d["steps"][2]["status"] == "pending"

    def test_to_dict_with_finished_at(self) -> None:
        job = DeployJob(
            job_id="finished",
            options={},
            status="done",
            finished_at=12345.678,
        )
        d = job.to_dict()
        assert d["finished_at"] == 12345.678

    def test_to_dict_with_none_finished_at(self) -> None:
        job = DeployJob(
            job_id="unfinished",
            options={},
            status="running",
        )
        d = job.to_dict()
        assert d["finished_at"] is None

    def test_to_dict_step_with_timestamps(self) -> None:
        step = DeployStep(
            id="check",
            label="Check",
            status="done",
            started_at=100.0,
            finished_at=101.0,
        )
        job = DeployJob(job_id="ts", options={}, steps=[step])
        d = job.to_dict()
        assert d["steps"][0]["started_at"] == 100.0
        assert d["steps"][0]["finished_at"] == 101.0


# ── _hub_remote_dir deep ─────────────────────────────────────────────────────


class TestHubRemoteDirDeep:
    def test_custom_dir_with_whitespace(self) -> None:
        with patch.dict(
            os.environ, {"FHD_PUSH_REMOTE_DIR": "  /custom/path  "}, clear=False
        ):
            result = _hub_remote_dir("stable")
        assert result == "/custom/path"

    def test_empty_custom_dir_falls_back(self) -> None:
        with patch.dict(
            os.environ, {"FHD_PUSH_REMOTE_DIR": "   "}, clear=False
        ):
            result = _hub_remote_dir("stable")
        assert result == "/var/www/update/releases/stable/server"
