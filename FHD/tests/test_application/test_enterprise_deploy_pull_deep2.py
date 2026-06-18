"""Deep coverage tests for app.application.enterprise_deploy_pull.

Targets remaining uncovered branches:
- _read_deployed_sha256 (file missing, read error)
- _read_local_manifest_file (file missing, invalid JSON, non-dict)
- _fetch_hub_manifest (local first, fetch fallback, fetch error)
- check_enterprise_updates (various flag combinations)
- PullStep defaults
- _execute_pull_job verify success path
- _execute_pull_job apply_backend with script present
- _execute_pull_job apply_frontend with vue dist present
- _execute_pull_job restart in production env
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
    _fetch_hub_manifest,
    _read_deployed_sha256,
    _read_local_manifest_file,
    _run_shell,
    check_enterprise_updates,
    get_pull_job,
    start_enterprise_pull,
)

# ── _read_deployed_sha256 ───────────────────────────────────────────────────


class TestReadDeployedSha256:
    def test_returns_empty_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(edp, "DEPLOY_ROOT", str(tmp_path))
        assert _read_deployed_sha256() == ""

    def test_reads_file(self, monkeypatch, tmp_path):
        (tmp_path / ".deploy-sha256").write_text("abc123\n")
        monkeypatch.setattr(edp, "DEPLOY_ROOT", str(tmp_path))
        assert _read_deployed_sha256() == "abc123"

    def test_strips_whitespace(self, monkeypatch, tmp_path):
        (tmp_path / ".deploy-sha256").write_text("  abc123  \n")
        monkeypatch.setattr(edp, "DEPLOY_ROOT", str(tmp_path))
        assert _read_deployed_sha256() == "abc123"

    def test_read_error_returns_empty(self, monkeypatch, tmp_path):
        # Create a directory instead of file → read fails
        (tmp_path / ".deploy-sha256").mkdir()
        monkeypatch.setattr(edp, "DEPLOY_ROOT", str(tmp_path))
        assert _read_deployed_sha256() == ""


# ── _read_local_manifest_file ───────────────────────────────────────────────


class TestReadLocalManifestFile:
    def test_returns_none_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(edp, "MANIFEST_PATH", str(tmp_path / "missing.json"))
        assert _read_local_manifest_file() is None

    def test_reads_dict(self, monkeypatch, tmp_path):
        f = tmp_path / "manifest.json"
        f.write_text(json.dumps({"sha256": "abc", "version": "1.0"}))
        monkeypatch.setattr(edp, "MANIFEST_PATH", str(f))
        result = _read_local_manifest_file()
        assert result == {"sha256": "abc", "version": "1.0"}

    def test_returns_none_for_non_dict(self, monkeypatch, tmp_path):
        f = tmp_path / "manifest.json"
        f.write_text(json.dumps([1, 2, 3]))
        monkeypatch.setattr(edp, "MANIFEST_PATH", str(f))
        assert _read_local_manifest_file() is None

    def test_returns_none_for_invalid_json(self, monkeypatch, tmp_path):
        f = tmp_path / "manifest.json"
        f.write_text("not json")
        monkeypatch.setattr(edp, "MANIFEST_PATH", str(f))
        assert _read_local_manifest_file() is None


# ── _fetch_hub_manifest ─────────────────────────────────────────────────────


class TestFetchHubManifest:
    def test_returns_local_first(self, monkeypatch, tmp_path):
        local_manifest = {"sha256": "local", "source": "local"}
        with patch.object(edp, "_read_local_manifest_file", return_value=local_manifest):
            result = _fetch_hub_manifest()
        assert result == local_manifest

    def test_fetches_from_url_when_no_local(self, monkeypatch):
        with patch.object(edp, "_read_local_manifest_file", return_value=None):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"sha256": "remote"}).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = _fetch_hub_manifest()
        assert result == {"sha256": "remote"}

    def test_returns_none_for_non_dict_response(self, monkeypatch):
        with patch.object(edp, "_read_local_manifest_file", return_value=None):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps([1, 2]).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = _fetch_hub_manifest()
        assert result is None

    def test_returns_none_on_fetch_error(self, monkeypatch):
        import urllib.error

        with patch.object(edp, "_read_local_manifest_file", return_value=None):
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("fail"),
            ):
                result = _fetch_hub_manifest()
        assert result is None


# ── check_enterprise_updates ────────────────────────────────────────────────


class TestCheckEnterpriseUpdatesDeep:
    def test_no_hub_manifest(self, monkeypatch):
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value=None),
            patch.object(edp, "_read_deployed_sha256", return_value=""),
        ):
            result = check_enterprise_updates()
        assert result["role"] == "enterprise"
        assert result["flags"]["needs_update"] is False
        assert result["flags"]["up_to_date"] is False
        assert result["update_hub"]["reachable"] is False

    def test_up_to_date(self, monkeypatch):
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value={"sha256": "abc"}),
            patch.object(edp, "_read_deployed_sha256", return_value="abc"),
        ):
            result = check_enterprise_updates()
        assert result["flags"]["needs_update"] is False
        assert result["flags"]["up_to_date"] is True

    def test_needs_update_when_different(self, monkeypatch):
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value={"sha256": "new"}),
            patch.object(edp, "_read_deployed_sha256", return_value="old"),
        ):
            result = check_enterprise_updates()
        assert result["flags"]["needs_update"] is True
        assert result["flags"]["up_to_date"] is False

    def test_needs_update_when_no_deployed(self, monkeypatch):
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value={"sha256": "new"}),
            patch.object(edp, "_read_deployed_sha256", return_value=""),
        ):
            result = check_enterprise_updates()
        assert result["flags"]["needs_update"] is True

    def test_no_update_when_no_hub_sha(self, monkeypatch):
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value={}),
            patch.object(edp, "_read_deployed_sha256", return_value=""),
        ):
            result = check_enterprise_updates()
        assert result["flags"]["needs_update"] is False
        assert result["flags"]["up_to_date"] is False

    def test_with_full_manifest(self, monkeypatch):
        manifest = {
            "sha256": "abc",
            "git_sha": "def123",
            "version": "1.0.0",
            "built_at": "2024-01-01",
        }
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value=manifest),
            patch.object(edp, "_read_deployed_sha256", return_value="abc"),
        ):
            result = check_enterprise_updates()
        assert result["update_hub"]["version"] == "1.0.0"
        assert result["update_hub"]["git_sha"] == "def123"
        assert result["update_hub"]["sha256"] == "abc"
        assert result["update_hub"]["built_at"] == "2024-01-01"

    def test_vue_dist_paths(self, monkeypatch, tmp_path):
        # Set up paths
        hub_vue = tmp_path / "hub_vue"
        hub_vue.mkdir()
        local_vue = tmp_path / "local_vue"
        local_vue.mkdir()
        monkeypatch.setattr(edp, "HUB_VUE_DIST", str(hub_vue))
        monkeypatch.setattr(edp, "LOCAL_VUE_DIST", str(local_vue))
        with (
            patch.object(edp, "_fetch_hub_manifest", return_value={"sha256": "abc"}),
            patch.object(edp, "_read_deployed_sha256", return_value="abc"),
        ):
            result = check_enterprise_updates()
        assert result["update_hub"]["has_vue_dist"] is True
        assert result["enterprise"]["has_vue_dist"] is True
        assert result["flags"]["hub_has_frontend"] is True


# ── PullStep defaults ───────────────────────────────────────────────────────


class TestPullStepDefaults:
    def test_defaults(self):
        step = PullStep(id="s1", label="Step 1")
        assert step.status == "pending"
        assert step.detail == ""
        assert step.started_at is None
        assert step.finished_at is None

    def test_with_values(self):
        step = PullStep(
            id="s1",
            label="Step 1",
            status="done",
            detail="ok",
            started_at=1.0,
            finished_at=2.0,
        )
        assert step.status == "done"
        assert step.detail == "ok"
        assert step.started_at == 1.0
        assert step.finished_at == 2.0


# ── PullJob defaults ────────────────────────────────────────────────────────


class TestPullJobDefaults:
    def test_defaults(self):
        job = PullJob(job_id="j1", options={})
        assert job.status == "queued"
        assert job.steps == []
        assert job.error == ""
        assert job.created_at > 0
        assert job.finished_at is None

    def test_to_dict_with_steps(self):
        step = PullStep(id="s1", label="Step 1", status="done", detail="ok")
        job = PullJob(
            job_id="j1",
            options={"k": "v"},
            status="done",
            steps=[step],
            error="",
            created_at=1.0,
            finished_at=2.0,
        )
        d = job.to_dict()
        assert d["job_id"] == "j1"
        assert d["status"] == "done"
        assert d["options"] == {"k": "v"}
        assert d["error"] == ""
        assert d["created_at"] == 1.0
        assert d["finished_at"] == 2.0
        assert len(d["steps"]) == 1
        assert d["steps"][0]["id"] == "s1"
        assert d["steps"][0]["label"] == "Step 1"
        assert d["steps"][0]["status"] == "done"
        assert d["steps"][0]["detail"] == "ok"
        assert d["steps"][0]["started_at"] is None
        assert d["steps"][0]["finished_at"] is None


# ── _execute_pull_job deep ──────────────────────────────────────────────────


class TestExecutePullJobDeep:
    @pytest.mark.asyncio
    async def test_verify_success_path(self, monkeypatch):
        """Verify step succeeds when up_to_date after pull."""
        call_count = {"n": 0}

        def fake_check():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {
                    "flags": {"needs_update": True, "up_to_date": False},
                    "update_hub": {"git_sha": "abc"},
                }
            # Second call (verify) → up to date
            return {
                "flags": {"needs_update": False, "up_to_date": True},
                "update_hub": {"git_sha": "abc"},
            }

        async def fake_run_shell(step, cmd, **kw):
            step.status = "done"
            step.detail = "ok"
            step.started_at = time.time()
            step.finished_at = time.time()

        with (
            patch.object(edp, "check_enterprise_updates", side_effect=fake_check),
            patch.object(edp, "_run_shell", side_effect=fake_run_shell),
            patch.object(edp, "Path") as mock_path_cls,
        ):
            mock_path = MagicMock()
            mock_path.is_file.return_value = True
            mock_path.is_dir.return_value = True
            mock_path.joinpath.return_value = mock_path
            mock_path.parent = mock_path
            mock_path_cls.return_value = mock_path
            mock_path_cls.side_effect = lambda *a, **kw: mock_path

            opts = {"force": False, "include_backend": True, "include_frontend": True}
            job = PullJob(job_id="j1", options=opts, steps=_build_pull_steps(opts))
            await _execute_pull_job(job)
        assert job.status == "done"
        verify_step = next(s for s in job.steps if s.id == "verify")
        assert verify_step.status == "done"
        assert verify_step.detail == "更新完成"

    @pytest.mark.asyncio
    async def test_apply_backend_with_script_present(self, monkeypatch):
        """apply_backend runs the script when it exists."""
        with patch.object(
            edp,
            "check_enterprise_updates",
            return_value={
                "flags": {"needs_update": True, "up_to_date": False},
                "update_hub": {"git_sha": "abc"},
            },
        ):
            executed_steps = []

            async def fake_run_shell(step, cmd, **kw):
                executed_steps.append((step.id, cmd))
                step.status = "done"
                step.detail = "ok"
                step.started_at = time.time()
                step.finished_at = time.time()

            with (
                patch.object(edp, "_run_shell", side_effect=fake_run_shell),
                patch.object(edp, "Path") as mock_path_cls,
            ):
                mock_path = MagicMock()
                mock_path.is_file.return_value = True
                mock_path.is_dir.return_value = False  # dev env (skip restart)
                mock_path.joinpath.return_value = mock_path
                mock_path.parent = mock_path
                mock_path_cls.return_value = mock_path
                mock_path_cls.side_effect = lambda *a, **kw: mock_path

                opts = {"force": False, "include_backend": True, "include_frontend": False}
                job = PullJob(job_id="j1", options=opts, steps=_build_pull_steps(opts))
                await _execute_pull_job(job)
        # apply_backend should have been called with bash script
        backend_calls = [c for s, c in executed_steps if s == "apply_backend"]
        assert len(backend_calls) == 1
        assert backend_calls[0][0] == "bash"

    @pytest.mark.asyncio
    async def test_apply_frontend_with_vue_dist(self, monkeypatch):
        """apply_frontend runs rsync when vue dist exists."""
        with patch.object(
            edp,
            "check_enterprise_updates",
            return_value={
                "flags": {"needs_update": True, "up_to_date": False},
                "update_hub": {"git_sha": "abc"},
            },
        ):
            executed_steps = []

            async def fake_run_shell(step, cmd, **kw):
                executed_steps.append((step.id, cmd))
                step.status = "done"
                step.detail = "ok"
                step.started_at = time.time()
                step.finished_at = time.time()

            with (
                patch.object(edp, "_run_shell", side_effect=fake_run_shell),
                patch.object(edp, "Path") as mock_path_cls,
            ):
                mock_path = MagicMock()
                mock_path.is_file.return_value = False
                mock_path.is_dir.return_value = True  # vue dist exists, dev env (no app dir)
                mock_path.joinpath.return_value = mock_path
                mock_path.parent = mock_path
                mock_path_cls.return_value = mock_path
                mock_path_cls.side_effect = lambda *a, **kw: mock_path

                opts = {"force": False, "include_backend": False, "include_frontend": True}
                job = PullJob(job_id="j1", options=opts, steps=_build_pull_steps(opts))
                await _execute_pull_job(job)
        # apply_frontend should have been called with rsync
        frontend_calls = [c for s, c in executed_steps if s == "apply_frontend"]
        assert len(frontend_calls) == 1
        assert frontend_calls[0][0] == "rsync"

    @pytest.mark.asyncio
    async def test_restart_in_production_env(self, monkeypatch):
        """restart runs systemctl when app dir exists."""
        with patch.object(
            edp,
            "check_enterprise_updates",
            return_value={
                "flags": {"needs_update": True, "up_to_date": False},
                "update_hub": {"git_sha": "abc"},
            },
        ):
            executed_steps = []

            async def fake_run_shell(step, cmd, **kw):
                executed_steps.append((step.id, cmd))
                step.status = "done"
                step.detail = "ok"
                step.started_at = time.time()
                step.finished_at = time.time()

            with (
                patch.object(edp, "_run_shell", side_effect=fake_run_shell),
                patch.object(edp, "Path") as mock_path_cls,
            ):
                mock_path = MagicMock()
                mock_path.is_file.return_value = False
                mock_path.is_dir.return_value = True  # app dir exists → production
                mock_path.joinpath.return_value = mock_path
                mock_path.parent = mock_path
                mock_path_cls.return_value = mock_path
                mock_path_cls.side_effect = lambda *a, **kw: mock_path

                opts = {"force": False, "include_backend": False, "include_frontend": False}
                job = PullJob(job_id="j1", options=opts, steps=_build_pull_steps(opts))
                await _execute_pull_job(job)
        # restart should have been called with systemctl
        restart_calls = [c for s, c in executed_steps if s == "restart"]
        assert len(restart_calls) == 1
        assert restart_calls[0][0] == "systemctl"

    @pytest.mark.asyncio
    async def test_check_step_failure_propagates(self, monkeypatch):
        """When check_enterprise_updates raises, job errors out."""
        with patch.object(edp, "check_enterprise_updates", side_effect=RuntimeError("check fail")):
            opts = {"force": False, "include_backend": True, "include_frontend": True}
            job = PullJob(job_id="j1", options=opts, steps=_build_pull_steps(opts))
            await _execute_pull_job(job)
        assert job.status == "error"
        assert "check fail" in job.error

    @pytest.mark.asyncio
    async def test_run_shell_error_propagates(self, monkeypatch):
        """When _run_shell raises, job errors out."""
        with patch.object(
            edp,
            "check_enterprise_updates",
            return_value={
                "flags": {"needs_update": True, "up_to_date": False},
                "update_hub": {"git_sha": "abc"},
            },
        ):

            async def failing_run_shell(step, cmd, **kw):
                step.status = "error"
                step.detail = "shell fail"
                step.started_at = time.time()
                step.finished_at = time.time()
                raise RuntimeError("shell fail")

            with (
                patch.object(edp, "_run_shell", side_effect=failing_run_shell),
                patch.object(edp, "Path") as mock_path_cls,
            ):
                mock_path = MagicMock()
                mock_path.is_file.return_value = True
                mock_path.is_dir.return_value = True
                mock_path.joinpath.return_value = mock_path
                mock_path.parent = mock_path
                mock_path_cls.return_value = mock_path
                mock_path_cls.side_effect = lambda *a, **kw: mock_path

                opts = {"force": False, "include_backend": True, "include_frontend": True}
                job = PullJob(job_id="j1", options=opts, steps=_build_pull_steps(opts))
                await _execute_pull_job(job)
        assert job.status == "error"
        assert "shell fail" in job.error


# ── _build_pull_steps deep ──────────────────────────────────────────────────


class TestBuildPullStepsDeep:
    def test_step_ids_in_order(self):
        steps = _build_pull_steps({"include_backend": True, "include_frontend": True})
        ids = [s.id for s in steps]
        assert ids == ["check", "apply_backend", "apply_frontend", "restart", "verify"]

    def test_step_labels(self):
        steps = _build_pull_steps({})
        for step in steps:
            assert step.label  # non-empty label

    def test_all_steps_pending_initially(self):
        steps = _build_pull_steps({})
        for step in steps:
            assert step.status == "pending"


# ── start_enterprise_pull deep ──────────────────────────────────────────────


class TestStartEnterprisePullDeep:
    @pytest.mark.asyncio
    async def test_generates_unique_job_ids(self, monkeypatch):
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

        async def fake_execute(job):
            job.status = "done"
            job.finished_at = time.time()
            edp._ACTIVE_PULL = None

        with patch.object(edp, "_execute_pull_job", new=fake_execute):
            job1 = await start_enterprise_pull({})
            await asyncio.sleep(0.05)
            edp._ACTIVE_PULL = None
            job2 = await start_enterprise_pull({})
            await asyncio.sleep(0.05)
        assert job1.job_id != job2.job_id
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

    @pytest.mark.asyncio
    async def test_options_override_defaults(self, monkeypatch):
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

        async def fake_execute(job):
            job.status = "done"
            job.finished_at = time.time()
            edp._ACTIVE_PULL = None

        with patch.object(edp, "_execute_pull_job", new=fake_execute):
            job = await start_enterprise_pull(
                {"include_backend": False, "include_frontend": False, "force": True}
            )
            await asyncio.sleep(0.05)
        assert job.options["include_backend"] is False
        assert job.options["include_frontend"] is False
        assert job.options["force"] is True
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

    @pytest.mark.asyncio
    async def test_job_added_to_jobs_dict(self, monkeypatch):
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None

        async def fake_execute(job):
            job.status = "done"
            job.finished_at = time.time()
            edp._ACTIVE_PULL = None

        with patch.object(edp, "_execute_pull_job", new=fake_execute):
            job = await start_enterprise_pull({})
            await asyncio.sleep(0.05)
        assert job.job_id in edp._PULL_JOBS
        edp._PULL_JOBS.clear()
        edp._ACTIVE_PULL = None
