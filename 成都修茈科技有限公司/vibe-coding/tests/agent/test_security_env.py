"""Tests for env scrubbing + sandbox env isolation."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from vibe_coding.agent.sandbox import (
    SandboxJob,
    SandboxPolicy,
    SubprocessSandboxDriver,
)
from vibe_coding.agent.security.env import DEFAULT_ENV_ALLOWLIST, sanitise_env


def test_sanitise_env_filters_secrets() -> None:
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/user",
        "OPENAI_API_KEY": "sk-secret",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "CUSTOM_VAR": "x",
    }
    out = sanitise_env(base=base)
    assert "OPENAI_API_KEY" not in out
    assert "AWS_SECRET_ACCESS_KEY" not in out
    assert "CUSTOM_VAR" not in out
    assert out["PATH"] == "/usr/bin"
    assert out["HOME"] == "/home/user"


def test_sanitise_env_extra_allow() -> None:
    base = {"PATH": "/x", "MY_VAR": "y"}
    out = sanitise_env(base=base, extra_allow=["MY_VAR"])
    assert out["MY_VAR"] == "y"


def test_sanitise_env_overrides_take_precedence() -> None:
    base = {"PATH": "/usr/bin"}
    out = sanitise_env(base=base, overrides={"PATH": "/custom/path", "EXTRA": "1"})
    assert out["PATH"] == "/custom/path"
    assert out["EXTRA"] == "1"


def test_sanitise_env_default_pythonioencoding() -> None:
    out = sanitise_env(base={"PATH": "/x"})
    assert out["PYTHONIOENCODING"] == "utf-8"


def test_sanitise_env_overrides_can_remove_via_none() -> None:
    out = sanitise_env(base={"PATH": "/x"}, overrides={"PATH": None})  # type: ignore[dict-item]
    assert "PATH" not in out


def test_default_allowlist_covers_essentials() -> None:
    for required in ("PATH", "HOME", "LANG", "TMPDIR", "PYTHONIOENCODING"):
        # Either in the static allow-list or always added by sanitise_env
        if required != "PYTHONIOENCODING":
            assert required in DEFAULT_ENV_ALLOWLIST


def test_subprocess_command_does_not_leak_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run a tiny script that prints whether OPENAI_API_KEY is visible."""
    monkeypatch.setenv("OPENAI_API_KEY", "leak-test-" + ("x" * 24))
    monkeypatch.setenv("MY_PRIVATE_TOKEN", "leaked-token")
    drv = SubprocessSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                "import os; print('OPENAI_API_KEY' in os.environ); print('MY_PRIVATE_TOKEN' in os.environ)",
            ],
        ),
        policy=SandboxPolicy(timeout_s=5),
    )
    assert res.success, res.stderr
    lines = res.stdout.strip().splitlines()
    assert lines == ["False", "False"], f"Sandbox leaked secrets! Output: {res.stdout!r}"


def test_subprocess_command_can_opt_in_to_env_var(tmp_path: Path) -> None:
    drv = SubprocessSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                "import os; print(os.environ.get('MY_OPT_IN', 'missing'))",
            ],
            env={"MY_OPT_IN": "explicit"},
        ),
        policy=SandboxPolicy(timeout_s=5),
    )
    assert res.success, res.stderr
    assert "explicit" in res.stdout


def test_subprocess_command_stdin_devnull(tmp_path: Path) -> None:
    """A tool that reads from stdin (without us providing one) must terminate."""
    drv = SubprocessSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                # Reading from stdin returns '' (EOF) immediately
                # because we wired stdin=DEVNULL.
                "import sys; data = sys.stdin.read(); print('eof' if not data else data)",
            ],
        ),
        policy=SandboxPolicy(timeout_s=5),
    )
    assert res.success, res.stderr
    assert "eof" in res.stdout


def test_subprocess_command_explicit_stdin_still_works(tmp_path: Path) -> None:
    drv = SubprocessSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                "import sys; print(sys.stdin.read())",
            ],
            stdin="hello\n",
        ),
        policy=SandboxPolicy(timeout_s=5),
    )
    assert res.success, res.stderr
    assert "hello" in res.stdout


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group ownership")
@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "interrupt"])
def test_command_descendants_cannot_write_after_return(tmp_path, monkeypatch, outcome):
    ready, release, late = (tmp_path / name for name in ("ready", "release", "late"))
    child = (
        f"import os,time;from pathlib import Path;p=Path({str(tmp_path)!r});"
        "(p/'pid.tmp').write_text(str(os.getpid()));(p/'pid.tmp').rename(p/'ready');deadline=time.monotonic()+10\n"
        "while not (p/'release').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "if (p/'release').exists(): (p/'late').write_text('after return')\n"
    )
    parent = (
        "import subprocess,sys,time;from pathlib import Path;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}],"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
        f"ready=Path({str(ready)!r})\n"
        "while not ready.exists(): time.sleep(.01)\n"
        + ("time.sleep(30)" if outcome in {"timeout", "interrupt"} else f"sys.exit({int(outcome == 'failure')})")
    )
    if outcome == "interrupt":
        communicate = subprocess.Popen.communicate
        interrupted = False

        def interrupt_after_child_starts(proc, *args, **kwargs):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise KeyboardInterrupt
            return communicate(proc, *args, **kwargs)

        monkeypatch.setattr(subprocess.Popen, "communicate", interrupt_after_child_starts)
    job = SandboxJob(kind="command", workspace_dir=str(tmp_path), command=[sys.executable, "-c", parent])
    try:
        if outcome == "interrupt":
            with pytest.raises(KeyboardInterrupt):
                SubprocessSandboxDriver().execute(job, SandboxPolicy(timeout_s=3))
        else:
            result = SubprocessSandboxDriver().execute(job, SandboxPolicy(timeout_s=3))
            assert result.success is (outcome == "success")
            assert result.exit_code == {"success": 0, "failure": 1, "timeout": 124}[outcome]
        assert ready.exists(), "the scenario must start a real descendant"
        release.touch()
        deadline = time.monotonic() + 0.5
        while not late.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not late.exists(), "descendant wrote after the command returned"
    finally:
        if ready.exists():
            with suppress(ProcessLookupError):
                os.kill(int(ready.read_text()), signal.SIGKILL)


def test_command_timeout_receipt_is_nonzero_and_bounded(tmp_path):
    result = SubprocessSandboxDriver().execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                "import sys,time;print('α'*4000,flush=True);print('β'*4000,file=sys.stderr,flush=True);time.sleep(30)",
            ],
        ),
        SandboxPolicy(timeout_s=2, max_output_size=32),
    )
    assert not result.success and result.error_type == "TimeoutError"
    assert result.exit_code != 0
    assert result.stdout.startswith("α" * 32) and result.stderr.startswith("β" * 32)
    assert len(result.stdout) < 100 and len(result.stderr) < 100


def test_missing_command_receipt_is_nonzero(tmp_path):
    result = SubprocessSandboxDriver().execute(
        SandboxJob(kind="command", workspace_dir=str(tmp_path), command=[str(tmp_path / "missing-command")])
    )
    assert not result.success and result.error_type == "FileNotFoundError"
    assert result.exit_code == 127


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable permissions")
def test_unexecutable_command_receipt_is_nonzero(tmp_path):
    command = tmp_path / "command"
    command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    command.chmod(0o600)
    result = SubprocessSandboxDriver().execute(
        SandboxJob(kind="command", workspace_dir=str(tmp_path), command=[str(command)])
    )
    assert not result.success and result.error_type == "PermissionError"
    assert result.exit_code == 126


@pytest.mark.parametrize("command,workspace", [([], True), (["unused"], False)])
def test_invalid_command_receipt_is_nonzero(tmp_path, command, workspace):
    result = SubprocessSandboxDriver().execute(
        SandboxJob(kind="command", workspace_dir=str(tmp_path) if workspace else None, command=command)
    )
    assert not result.success and result.error_type == "ValueError"
    assert result.exit_code == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group ownership")
def test_descendant_pipe_cannot_extend_command_deadline(tmp_path):
    started = time.monotonic()
    result = SubprocessSandboxDriver().execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                "import subprocess,sys;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])",
            ],
        ),
        SandboxPolicy(timeout_s=2),
    )
    assert result.error_type == "TimeoutError" and result.exit_code == 124
    assert time.monotonic() - started < 6


def test_workspace_root_rejected(tmp_path: Path) -> None:
    """Trying to sandbox a filesystem root must fail loudly."""
    from vibe_coding.agent.sandbox.driver import resolve_workspace

    if os.name == "nt":
        # Skip on Windows because finding "the" filesystem root is brittle.
        pytest.skip("posix-only root rejection check")
    with pytest.raises(ValueError, match=r"filesystem root|directory"):
        resolve_workspace("/")


def test_workspace_nul_byte_rejected(tmp_path: Path) -> None:
    from vibe_coding.agent.sandbox.driver import resolve_workspace

    with pytest.raises(ValueError, match=r"NUL"):
        resolve_workspace(str(tmp_path) + "\x00/foo")
