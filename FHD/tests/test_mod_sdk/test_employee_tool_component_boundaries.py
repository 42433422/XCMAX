"""Employee tool resources and write targets must match the authorized operation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.mod_sdk import employee_specialized_tools as tools
from app.mod_sdk.employee_tools import quality
from app.mod_sdk.employee_tools.ports import QualityPorts


@pytest.mark.parametrize("failure", ["cancel", "communication", "timeout", "success"])
async def test_command_runner_reaps_its_owned_process(monkeypatch, failure):
    create_process = asyncio.create_subprocess_exec
    spawned: list[asyncio.subprocess.Process] = []
    ready = asyncio.Event()

    async def capture(*args, **kwargs):
        process = await create_process(*args, **kwargs)
        spawned.append(process)
        if failure == "communication":
            monkeypatch.setattr(
                process, "communicate", AsyncMock(side_effect=OSError("pipe error"))
            )
        ready.set()
        return process

    monkeypatch.setattr(tools.asyncio, "create_subprocess_exec", capture)
    code = "print('complete')" if failure == "success" else "import time; time.sleep(30)"
    task = asyncio.create_task(
        tools._run_cmd([sys.executable, "-c", code], timeout=1 if failure == "timeout" else 5)
    )
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result["ok"] is (failure == "success")
            if failure == "success":
                assert result["stdout"] == "complete\n"
        assert spawned[0].returncode is not None
    finally:
        if not task.done():
            task.cancel()
        for process in spawned:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def test_repeated_cancellation_waits_for_owned_process_cleanup(monkeypatch):
    create_process = asyncio.create_subprocess_exec
    process_ready = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()
    spawned: list[asyncio.subprocess.Process] = []

    async def capture(*args, **kwargs):
        process = await create_process(*args, **kwargs)
        spawned.append(process)
        wait = process.wait

        async def delayed_wait():
            cleanup_started.set()
            await release_cleanup.wait()
            result = await wait()
            cleanup_finished.set()
            return result

        monkeypatch.setattr(process, "wait", delayed_wait)
        process_ready.set()
        return process

    monkeypatch.setattr(tools.asyncio, "create_subprocess_exec", capture)
    task = asyncio.create_task(
        tools._run_cmd([sys.executable, "-c", "import time; time.sleep(30)"])
    )
    try:
        await asyncio.wait_for(process_ready.wait(), timeout=5)
        task.cancel()
        await asyncio.wait_for(cleanup_started.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleanup_finished.is_set()
        assert spawned[0].returncode is not None
    finally:
        release_cleanup.set()
        if not task.done():
            task.cancel()
        for process in spawned:
            if process.returncode is None:
                process.kill()
            await process.wait()
        await asyncio.gather(task, return_exceptions=True)


async def test_quality_component_runs_with_its_own_inputs(tmp_path, monkeypatch):
    facade_runner = AsyncMock(side_effect=AssertionError("public facade must not be consulted"))
    monkeypatch.setattr(tools, "_run_cmd", facade_runner)
    runner = AsyncMock(
        return_value={"ok": True, "returncode": 0, "stdout": "local checks passed", "stderr": ""}
    )
    script = AsyncMock(side_effect=AssertionError("pytest is not a script operation"))
    ports = QualityPorts(tmp_path, tmp_path / "scripts", "local-python", runner, script)

    result = await quality.run_pytest(
        ports, {"args": ["local_tests/", "-x"], "env": {"CHECK_SCOPE": "local"}, "timeout": 7}, {}
    )

    assert result["ok"] is True
    assert result["stdout"] == "local checks passed"
    runner.assert_awaited_once_with(
        ["local-python", "-m", "pytest", "local_tests/", "-x"],
        cwd=tmp_path,
        timeout=7,
        env={"XCAGI_SKIP_LEGACY_COMPAT_ROUTES": "1", "CHECK_SCOPE": "local"},
    )
    facade_runner.assert_not_awaited()
    script.assert_not_awaited()


@pytest.mark.parametrize(
    "config",
    [
        'model = "root-model"\nmodel_reasoning_effort = "high"\n',
        'model_reasoning_effort = "high"\nmodel = "root-model"\n',
        'model = "root-model"\nmodel_reasoning_effort = "high"\n'
        '[profiles.secondary]\nmodel = "profile-model"\nmodel_reasoning_effort = "low"\n',
    ],
)
async def test_codex_usage_reads_top_level_config_keys(tmp_path, monkeypatch, config):
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(config)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    result = await tools.tool_query_codex_usage({}, {})

    assert result["config"] == {"model": "root-model", "reasoning_effort": "high"}
    assert result["codex_summary"]["model"] == "root-model"
    assert result["sources"] == ["config-toml"]


@pytest.fixture
def patch_workspace(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    for name in ("allowed.txt", "other.txt"):
        (root / name).write_text("before\n")
    return root


def _patch(name: str) -> str:
    return (
        f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-before\n+after\n"
    )


@pytest.mark.parametrize("mixed", [False, True])
async def test_patch_rejects_unapproved_diff_targets_before_writing(patch_workspace, mixed):
    root = patch_workspace
    patch = (_patch("allowed.txt") if mixed else "") + _patch("other.txt")

    result = await tools.tool_patch_file(
        {"path": "allowed.txt", "patch": patch, "confirm": True},
        {"workspace_root": str(root)},
    )

    assert (root / "allowed.txt").read_text() == "before\n"
    assert (root / "other.txt").read_text() == "before\n"
    assert result["ok"] is False


async def test_patch_changes_the_requested_file_only(patch_workspace):
    root = patch_workspace
    result = await tools.tool_patch_file(
        {"path": "allowed.txt", "patch": _patch("allowed.txt"), "confirm": True},
        {"workspace_root": str(root)},
    )

    assert result["ok"] is True
    assert (root / "allowed.txt").read_text() == "after\n"
    assert (root / "other.txt").read_text() == "before\n"
    assert not list(root.glob(".tmp-patch-*.diff"))


async def test_concurrent_patches_own_distinct_temporary_files(patch_workspace, monkeypatch):
    root = patch_workspace
    run_command = tools._run_cmd
    checks = 0
    both_ready = asyncio.Event()

    async def concurrent_check(args, **kwargs):
        nonlocal checks
        if "--check" in args:
            checks += 1
            if checks == 2:
                both_ready.set()
            await asyncio.wait_for(both_ready.wait(), timeout=5)
        return await run_command(args, **kwargs)

    monkeypatch.setattr(tools, "_run_cmd", concurrent_check)
    results = await asyncio.gather(
        *(
            tools.tool_patch_file(
                {"path": name, "patch": _patch(name), "confirm": True},
                {"workspace_root": str(root)},
            )
            for name in ("allowed.txt", "other.txt")
        )
    )

    assert all(result["ok"] for result in results)
    assert (root / "allowed.txt").read_text() == "after\n"
    assert (root / "other.txt").read_text() == "after\n"
    assert not list(root.glob(".tmp-patch-*.diff"))


async def test_patch_cleanup_preserves_preexisting_file(patch_workspace):
    root = patch_workspace
    sentinel = root / f".tmp-patch-{os.getpid()}.diff"
    sentinel.write_text("owned by another operation\n")

    result = await tools.tool_patch_file(
        {"path": "allowed.txt", "patch": _patch("allowed.txt"), "confirm": True},
        {"workspace_root": str(root)},
    )

    assert result["ok"] is True
    assert sentinel.is_file()
    assert sentinel.read_text() == "owned by another operation\n"


@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
async def test_log_reader_stays_inside_its_log_directory(tmp_path, monkeypatch, escape):
    root = tmp_path / "fhd"
    logs = root / "logs"
    logs.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private synthetic fixture\n")
    monkeypatch.setattr(tools, "_FHD_ROOT", root)
    if escape == "symlink":
        (logs / "linked.log").symlink_to(outside)
        name = "linked.log"
    else:
        name = "../../outside.txt" if escape == "relative" else str(outside)

    result = await tools.tool_tail_logs({"file": name}, {})

    assert result["ok"] is False
    assert "private synthetic fixture" not in str(result)
    assert outside.read_text() == "private synthetic fixture\n"


@pytest.mark.parametrize("escape", ["parent", "symlink"])
async def test_script_category_cannot_leave_scripts_directory(tmp_path, monkeypatch, escape):
    root = tmp_path / "fhd"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.py").write_text("VALUE = 1\n")
    (root / "private.py").write_text("VALUE = 2\n")
    monkeypatch.setattr(tools, "_FHD_ROOT", root)
    if escape == "symlink":
        (scripts / "linked").symlink_to(outside, target_is_directory=True)
        category = "linked"
    else:
        category = ".."

    result = await tools.tool_list_scripts({"category": category}, {})

    assert result["ok"] is False
