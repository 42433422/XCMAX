"""Tests for env scrubbing + sandbox env isolation."""

from __future__ import annotations

import os
import sys
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


def test_subprocess_command_does_not_leak_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Run a tiny script that prints whether OPENAI_API_KEY is visible."""
    monkeypatch.setenv("OPENAI_API_KEY", "leaked-secret-12345")
    monkeypatch.setenv("MY_PRIVATE_TOKEN", "leaked-token")
    drv = SubprocessSandboxDriver()
    res = drv.execute(
        SandboxJob(
            kind="command",
            workspace_dir=str(tmp_path),
            command=[
                sys.executable,
                "-c",
                "import os; print('OPENAI_API_KEY' in os.environ); "
                "print('MY_PRIVATE_TOKEN' in os.environ)",
            ],
        ),
        policy=SandboxPolicy(timeout_s=5),
    )
    assert res.success, res.stderr
    lines = res.stdout.strip().splitlines()
    assert lines == ["False", "False"], (
        f"Sandbox leaked secrets! Output: {res.stdout!r}"
    )


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
