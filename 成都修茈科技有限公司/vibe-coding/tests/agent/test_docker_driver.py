"""Tests for :class:`DockerSandboxDriver`.

Most assertions are gated on Docker being available because we cannot
exercise the run path otherwise. The driver's pure-Python helpers
(`_docker_path`, argument synthesis, JSON extraction) are still verified
unconditionally.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from vibe_coding.agent.sandbox import (
    DockerSandboxDriver,
    SandboxJob,
    SandboxPolicy,
    create_default_driver,
)
from vibe_coding.agent.sandbox.docker_driver import _docker_path, _extract_json
from vibe_coding.agent.sandbox.driver import docker_available


def test_docker_path_posix(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("posix-only path translation")
    assert _docker_path(tmp_path) == str(tmp_path.resolve())


def test_docker_path_windows() -> None:
    if os.name != "nt":
        pytest.skip("windows-only path translation")
    out = _docker_path(Path("C:/Users/me/proj"))
    assert out.lower().startswith("/c/")


def test_extract_json_handles_stray_logs() -> None:
    out = "spam line\nmore noise\n{\"success\": true, \"output\": {}}\n"
    data = _extract_json(out)
    assert data is not None and data["success"] is True


def test_extract_json_returns_none_on_garbage() -> None:
    assert _extract_json("nothing useful here") is None


# ----------------------------------------------------- resource flags


def test_build_run_args_emits_strict_resource_caps(tmp_path: Path) -> None:
    """The driver must set memory / swap / cpus / pids / cap-drop on every job."""
    driver = DockerSandboxDriver(image="python:3.11-slim")
    args = driver._build_run_args(  # type: ignore[attr-defined]
        pol=SandboxPolicy(
            timeout_s=10,
            memory_mb=128,
            cpu_limit=0.5,
            pids_limit=32,
            tmpfs_size_mb=32,
        ),
        workspace=tmp_path,
        read_only_workspace=True,
        image="python:3.11-slim",
    )
    joined = " ".join(args)
    assert "--memory=128m" in joined
    # Default swap == memory so swap-based escapes don't bypass the cap.
    assert "--memory-swap=128m" in joined
    assert "--memory-swappiness=0" in joined
    assert "--cpus=0.50" in joined
    assert "--pids-limit=32" in joined
    assert "--cap-drop=ALL" in joined
    assert "--security-opt=no-new-privileges" in joined
    assert "--read-only" in joined
    assert "--tmpfs=/tmp:rw,size=32m" in joined
    assert "--network=none" in joined


def test_build_run_args_passes_ulimits(tmp_path: Path) -> None:
    driver = DockerSandboxDriver()
    args = driver._build_run_args(  # type: ignore[attr-defined]
        pol=SandboxPolicy(
            ulimits=("nofile=512:512", "nproc=16:16", "fsize=10485760"),
        ),
        workspace=tmp_path,
        read_only_workspace=True,
        image="python:3.11-slim",
    )
    # Each ulimit appears as ``--ulimit nofile=512:512``.
    pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1) if args[i] == "--ulimit"]
    spec_set = {pair[1] for pair in pairs}
    assert {"nofile=512:512", "nproc=16:16", "fsize=10485760"} <= spec_set


def test_build_run_args_honours_cpu_period_quota(tmp_path: Path) -> None:
    driver = DockerSandboxDriver()
    args = driver._build_run_args(  # type: ignore[attr-defined]
        pol=SandboxPolicy(cpu_period_us=100_000, cpu_quota_us=50_000),
        workspace=tmp_path,
        read_only_workspace=True,
        image="python:3.11-slim",
    )
    joined = " ".join(args)
    assert "--cpu-period=100000" in joined
    assert "--cpu-quota=50000" in joined


def test_build_run_args_extra_writable_tmpfs(tmp_path: Path) -> None:
    driver = DockerSandboxDriver()
    args = driver._build_run_args(  # type: ignore[attr-defined]
        pol=SandboxPolicy(allow_write_paths=("/tmp", "/var/cache/pip")),
        workspace=tmp_path,
        read_only_workspace=True,
        image="python:3.11-slim",
    )
    # The extra tmpfs is added as two separate argv entries:
    # ``--tmpfs`` and ``/var/cache/pip:rw,size=...``.
    pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1) if args[i] == "--tmpfs"]
    targets = {pair[1].split(":")[0] for pair in pairs}
    assert "/var/cache/pip" in targets


def test_policy_swap_overrides_memory(tmp_path: Path) -> None:
    driver = DockerSandboxDriver()
    args = driver._build_run_args(  # type: ignore[attr-defined]
        pol=SandboxPolicy(memory_mb=200, memory_swap_mb=200),
        workspace=tmp_path,
        read_only_workspace=True,
        image="python:3.11-slim",
    )
    joined = " ".join(args)
    assert "--memory=200m" in joined
    assert "--memory-swap=200m" in joined


def test_default_driver_docker_when_available() -> None:
    drv = create_default_driver(prefer="auto")
    assert drv.name in {"docker", "subprocess"}


def test_docker_unavailable_yields_explicit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    drv = DockerSandboxDriver()
    monkeypatch.setattr(drv, "is_available", lambda: False)
    res = drv.execute(SandboxJob(kind="command", workspace_dir=".", command=["true"]))
    assert not res.success
    assert "docker" in res.error_message.lower()


def _image_available(image: str) -> bool:
    """Return True only when the image is already in the local daemon cache."""
    if not docker_available():
        return False
    import subprocess as _sp
    try:
        result = _sp.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(
    not _image_available("python:3.11-slim"),
    reason="python:3.11-slim not in local docker cache",
)
def test_docker_function_mode(tmp_path: Path) -> None:
    drv = DockerSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="function",
            source_code="def run(value):\n    return {'echo': value}\n",
            function_name="run",
            input_data={"value": "hi"},
        ),
        policy=SandboxPolicy(timeout_s=120, memory_mb=128),
    )
    assert res.success, res.stderr
    assert res.output == {"echo": "hi"}


@pytest.mark.skipif(
    not _image_available("alpine:3.19"),
    reason="alpine:3.19 not in local docker cache",
)
def test_docker_command_mode_with_bind_mount(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("hello", encoding="utf-8")
    drv = DockerSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=["sh", "-c", "ls /work && cat /work/marker.txt"],
            image="alpine:3.19",
        ),
        policy=SandboxPolicy(timeout_s=60),
    )
    assert res.success, res.stderr
    assert "marker.txt" in res.stdout
    assert "hello" in res.stdout
