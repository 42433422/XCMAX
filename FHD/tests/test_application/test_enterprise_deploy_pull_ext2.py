"""Tests for app.application.enterprise_deploy_pull — coverage ramp ext2.

Covers ``_run_shell``, ``_build_pull_steps``, ``_execute_pull_job`` (force
path, apply_backend skip, apply_frontend skip, restart skip, verify failure),
``start_enterprise_pull`` (lock contention), and ``get_pull_job``.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application import enterprise_deploy_pull as edp
from app.application.enterprise_deploy_pull import (
    PullJob,
    PullStep,
    _build_pull_steps,
    _execute_pull_job,
    _run_shell,
    get_pull_job,
    start_enterprise_pull,
)

# ── _run_shell ───────────────────────────────────────────────────────────────


class TestRunShell:
    @pytest.mark.asyncio
    async def test_success(self):
        step = PullStep(id="test", label="test")
        # Mock subprocess that exits 0
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(return_value=b"")  # EOF
        mock_proc.wait = AsyncMock(return_value=0)

        with patch(
            "app.application.enterprise_deploy_pull.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            await _run_shell(step, ["echo", "hi"])
        assert step.status == "done"
        assert step.started_at is not None
        assert step.finished_at is not None

    @pytest.mark.asyncio
    async def test_failure_nonzero_exit(self):
        step = PullStep(id="test", label="test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        # First call returns data, second returns empty (to break the loop)
        mock_proc.stdout.readline = AsyncMock(side_effect=[b"error output\n", b""])
        mock_proc.wait = AsyncMock(return_value=1)

        with patch(
            "app.application.enterprise_deploy_pull.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            with pytest.raises(RuntimeError):
                await _run_shell(step, ["false"])
        assert step.status == "error"
        assert "error output" in step.detail or "exit" in step.detail

    @pytest.mark.asyncio
    async def test_subprocess_error(self):
        step = PullStep(id="test", label="test")
        with patch(
            "app.application.enterprise_deploy_pull.asyncio.create_subprocess_exec",
            side_effect=OSError("spawn fail"),
        ):
            with pytest.raises(OSError):
                await _run_shell(step, ["bad"])
        assert step.status == "error"
        assert "spawn fail" in step.detail

    @pytest.mark.asyncio
    async def test_captures_tail_output(self):
        step = PullStep(id="test", label="test")
        mock_proc = MagicMock()
        mock_proc.stdout = MagicMock()
        # Multiple lines then EOF
        mock_proc.stdout.readline = AsyncMock(side_effect=[b"line1\n", b"line2\n", b"line3\n", b""])
        mock_proc.wait = AsyncMock(return_value=0)

        with patch(
            "app.application.enterprise_deploy_pull.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            await _run_shell(step, ["echo"])
        assert step.status == "done"
        assert "line3" in step.detail


# ── _build_pull_steps ────────────────────────────────────────────────────────


class TestBuildPullSteps:
    def test_default_includes_all(self):
        steps = _build_pull_steps({})
        ids = [s.id for s in steps]
        assert "check" in ids
        assert "apply_backend" in ids
        assert "apply_frontend" in ids
        assert "restart" in ids
        assert "verify" in ids

    def test_exclude_backend(self):
        steps = _build_pull_steps({"include_backend": False})
        ids = [s.id for s in steps]
        assert "apply_backend" not in ids
        assert "apply_frontend" in ids

    def test_exclude_frontend(self):
        steps = _build_pull_steps({"include_frontend": False})
        ids = [s.id for s in steps]
        assert "apply_frontend" not in ids
        assert "apply_backend" in ids

    def test_exclude_both(self):
        steps = _build_pull_steps({"include_backend": False, "include_frontend": False})
        ids = [s.id for s in steps]
        assert "apply_backend" not in ids
        assert "apply_frontend" not in ids
        assert "check" in ids
        assert "restart" in ids
        assert "verify" in ids


# ── _execute_pull_job ────────────────────────────────────────────────────────


class TestExecutePullJob:
    @pytest.mark.asyncio
    async def test_force_when_up_to_date(self, tmp_path, monkeypatch):
        # Force "up to date" by mocking check_enterprise_updates
        with patch(
            "app.application.enterprise_deploy_pull.check_enterprise_updates",
            return_value={
                "flags": {"needs_update": False, "up_to_date": True},
                "update_hub": {"git_sha": "abc"},
            },
        ):
            opts = {"force": False, "include_backend": True, "include_frontend": True}
            job = PullJob(
                job_id="j1",
                options=opts,
                steps=_build_pull_steps(opts),
            )
            await _execute_pull_job(job)
        assert job.status == "done"
        # Subsequent steps should be skipped
        skipped = [s for s in job.steps if s.status == "skipped"]
        assert len(skipped) > 0

    @pytest.mark.asyncio
    async def test_force_pull_even_when_up_to_date(self, tmp_path, monkeypatch):
        with patch(
            "app.application.enterprise_deploy_pull.check_enterprise_updates",
            return_value={
                "flags": {"needs_update": False, "up_to_date": True},
                "update_hub": {"git_sha": "abc"},
            },
        ):
            opts = {"force": True, "include_backend": True, "include_frontend": True}
            job = PullJob(
                job_id="j1",
                options=opts,
                steps=_build_pull_steps(opts),
            )

            # Mock _run_shell to avoid actually running shell commands
            async def fake_run_shell(step, cmd, **kwargs):
                step.status = "done"
                step.started_at = time.time()
                step.finished_at = time.time()

            with (
                patch(
                    "app.application.enterprise_deploy_pull._run_shell",
                    new=fake_run_shell,
                ),
                patch("app.application.enterprise_deploy_pull.Path") as mock_path_cls,
            ):
                # Make Path(...).is_file() / is_dir() return True
                mock_path = MagicMock()
                mock_path.is_file.return_value = True
                mock_path.is_dir.return_value = True
                mock_path.joinpath.return_value = mock_path
                mock_path.parent = mock_path
                mock_path_cls.return_value = mock_path
                mock_path_cls.side_effect = lambda *a, **kw: mock_path
                await _execute_pull_job(job)
        assert job.status == "done"

    @pytest.mark.asyncio
    async def test_apply_backend_skipped_when_no_script(self, tmp_path, monkeypatch):
        with (
            patch(
                "app.application.enterprise_deploy_pull.check_enterprise_updates",
                return_value={
                    "flags": {"needs_update": True, "up_to_date": False},
                    "update_hub": {"git_sha": "abc"},
                },
            ),
            patch("app.application.enterprise_deploy_pull.Path") as mock_path_cls,
        ):
            mock_path = MagicMock()
            mock_path.is_file.return_value = False  # No script
            mock_path.is_dir.return_value = False  # No deploy root
            mock_path.joinpath.return_value = mock_path
            mock_path.parent = mock_path
            mock_path_cls.return_value = mock_path
            mock_path_cls.side_effect = lambda *a, **kw: mock_path

            opts = {
                "force": False,
                "include_backend": True,
                "include_frontend": True,
            }
            job = PullJob(
                job_id="j1",
                options=opts,
                steps=_build_pull_steps(opts),
            )
            await _execute_pull_job(job)
        # apply_backend should be skipped
        backend_step = next(s for s in job.steps if s.id == "apply_backend")
        assert backend_step.status == "skipped"

    @pytest.mark.asyncio
    async def test_apply_frontend_skipped_when_no_vue_dist(self, monkeypatch):
        with (
            patch(
                "app.application.enterprise_deploy_pull.check_enterprise_updates",
                return_value={
                    "flags": {"needs_update": True, "up_to_date": False},
                    "update_hub": {"git_sha": "abc"},
                },
            ),
            patch("app.application.enterprise_deploy_pull.Path") as mock_path_cls,
        ):
            mock_path = MagicMock()
            mock_path.is_file.return_value = False
            mock_path.is_dir.return_value = False  # No vue dist
            mock_path.joinpath.return_value = mock_path
            mock_path.parent = mock_path
            mock_path_cls.return_value = mock_path
            mock_path_cls.side_effect = lambda *a, **kw: mock_path

            opts = {
                "force": False,
                "include_backend": True,
                "include_frontend": True,
            }
            job = PullJob(
                job_id="j1",
                options=opts,
                steps=_build_pull_steps(opts),
            )
            await _execute_pull_job(job)
        frontend_step = next(s for s in job.steps if s.id == "apply_frontend")
        assert frontend_step.status == "skipped"

    @pytest.mark.asyncio
    async def test_restart_skipped_in_dev_env(self, monkeypatch):
        with (
            patch(
                "app.application.enterprise_deploy_pull.check_enterprise_updates",
                return_value={
                    "flags": {"needs_update": True, "up_to_date": False},
                    "update_hub": {"git_sha": "abc"},
                },
            ),
            patch("app.application.enterprise_deploy_pull.Path") as mock_path_cls,
        ):
            mock_path = MagicMock()
            mock_path.is_file.return_value = False
            # No app dir → dev env
            mock_path.is_dir.return_value = False
            mock_path.joinpath.return_value = mock_path
            mock_path.parent = mock_path
            mock_path_cls.return_value = mock_path
            mock_path_cls.side_effect = lambda *a, **kw: mock_path

            opts = {
                "force": False,
                "include_backend": True,
                "include_frontend": True,
            }
            job = PullJob(
                job_id="j1",
                options=opts,
                steps=_build_pull_steps(opts),
            )
            await _execute_pull_job(job)
        restart_step = next(s for s in job.steps if s.id == "restart")
        assert restart_step.status == "skipped"

    @pytest.mark.asyncio
    async def test_verify_failure_raises(self, monkeypatch):
        # When verify fails in production env, RuntimeError is raised internally
        # but caught by the _DEPLOY_ERRORS handler, setting job.status to "error".
        # Mock _run_shell to succeed for all steps, and check_enterprise_updates
        # to return needs_update=True on both calls (check + verify).
        call_count = {"n": 0}

        def fake_check():
            call_count["n"] += 1
            return {
                "flags": {"needs_update": True, "up_to_date": False},
                "update_hub": {"git_sha": "abc"},
            }

        async def fake_run_shell(step, cmd, **kw):
            step.status = "done"
            step.detail = "ok"
            step.started_at = time.time()
            step.finished_at = time.time()

        with (
            patch(
                "app.application.enterprise_deploy_pull.check_enterprise_updates",
                side_effect=fake_check,
            ),
            patch(
                "app.application.enterprise_deploy_pull._run_shell",
                side_effect=fake_run_shell,
            ),
            patch("app.application.enterprise_deploy_pull.Path") as mock_path_cls,
        ):
            mock_path = MagicMock()
            mock_path.is_file.return_value = True
            mock_path.is_dir.return_value = True  # production env
            mock_path.joinpath.return_value = mock_path
            mock_path.parent = mock_path
            mock_path_cls.return_value = mock_path
            mock_path_cls.side_effect = lambda *a, **kw: mock_path

            opts = {
                "force": False,
                "include_backend": True,
                "include_frontend": True,
            }
            job = PullJob(
                job_id="j1",
                options=opts,
                steps=_build_pull_steps(opts),
            )
            # Verify step fails (needs_update still True) and production env.
            # RuntimeError is raised internally but caught by _DEPLOY_ERRORS handler.
            await _execute_pull_job(job)
        # Verify step should be error since needs_update still True
        verify_step = next(s for s in job.steps if s.id == "verify")
        assert verify_step.status == "error"
        assert job.status == "error"


# ── start_enterprise_pull ────────────────────────────────────────────────────


class TestStartEnterprisePull:
    @pytest.mark.asyncio
    async def test_starts_job(self, monkeypatch):
        # Reset state
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

        # Mock _execute_pull_job to avoid actual execution
        async def fake_execute(job):
            job.status = "done"
            job.finished_at = time.time()

        with patch(
            "app.application.enterprise_deploy_pull._execute_pull_job",
            new=fake_execute,
        ):
            job = await start_enterprise_pull({"force": False})
        assert job.job_id
        assert job in edp._PULL_JOBS.values()
        # Wait a tick for the task to run
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_default_options(self, monkeypatch):
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

        async def fake_execute(job):
            job.status = "done"
            job.finished_at = time.time()

        with patch(
            "app.application.enterprise_deploy_pull._execute_pull_job",
            new=fake_execute,
        ):
            job = await start_enterprise_pull(None)
        assert job.options["include_backend"] is True
        assert job.options["include_frontend"] is True
        assert job.options["force"] is False
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_lock_contention(self, monkeypatch):
        edp._PULL_JOBS.clear()
        # Simulate an active running job
        running_job = PullJob(job_id="running", options={})
        running_job.status = "running"
        edp._PULL_JOBS["running"] = running_job
        edp._ACTIVE_PULL = "running"

        with pytest.raises(RuntimeError, match="已有拉取任务进行中"):
            await start_enterprise_pull({})
        # Cleanup
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

    @pytest.mark.asyncio
    async def test_lock_released_after_completion(self, monkeypatch):
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

        async def fake_execute(job):
            job.status = "done"
            job.finished_at = time.time()
            # _execute_pull_job sets _ACTIVE_PULL = None in its finally block
            edp._ACTIVE_PULL = None

        with patch(
            "app.application.enterprise_deploy_pull._execute_pull_job",
            new=fake_execute,
        ):
            await start_enterprise_pull({})
            await asyncio.sleep(0.05)
        # _ACTIVE_PULL should be None after completion
        assert edp._ACTIVE_PULL is None


# ── get_pull_job ─────────────────────────────────────────────────────────────


class TestGetPullJob:
    def test_returns_existing(self):
        edp._PULL_JOBS.clear()
        job = PullJob(job_id="j1", options={})
        edp._PULL_JOBS["j1"] = job
        assert get_pull_job("j1") is job

    def test_returns_none_for_missing(self):
        edp._PULL_JOBS.clear()
        assert get_pull_job("missing") is None


# ── PullJob.to_dict ──────────────────────────────────────────────────────────


class TestPullJobToDict:
    def test_serialization(self):
        job = PullJob(
            job_id="j1",
            options={"k": "v"},
            status="done",
            steps=[PullStep(id="s1", label="step 1", status="done")],
        )
        d = job.to_dict()
        assert d["job_id"] == "j1"
        assert d["status"] == "done"
        assert d["options"] == {"k": "v"}
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "s1"
        assert d["steps"][0]["label"] == "step 1"
        assert d["steps"][0]["status"] == "done"
