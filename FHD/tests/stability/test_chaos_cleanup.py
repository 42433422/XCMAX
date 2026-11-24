"""Exercise the real drill CLI with a disposable external command receiver."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

DRILL = (
    Path(__file__).resolve().parents[3]
    / "成都修茈科技有限公司/MODstore_deploy/chaos/chaos_drill.py"
)


@pytest.mark.parametrize("failure", ["dry_run", "inject", "recover", "cancel", "none"])
def test_drill_recovers_partial_injection_and_cancellation(tmp_path, failure):
    state, calls = tmp_path / "state", tmp_path / "calls"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "action = sys.argv[2]\n"
        "with pathlib.Path(os.environ['DRILL_CALLS']).open('a') as f: f.write(action + '\\n')\n"
        "if action == 'stop': pathlib.Path(os.environ['DRILL_STATE']).write_text('stopped')\n"
        "failure = os.environ['DRILL_FAILURE']\n"
        "if (action == 'stop' and failure == 'inject') or (action == 'up' and failure == 'recover'): sys.exit(7)\n"
        "if action == 'up': pathlib.Path(os.environ['DRILL_STATE']).write_text('running')\n"
    )
    docker.chmod(0o755)
    command = [
        sys.executable,
        str(DRILL),
        "--scenario",
        "redis-stop",
        "--skip-smoke",
        "--duration",
        "60" if failure == "cancel" else "0",
    ]
    if failure != "dry_run":
        command.append("--confirm")
    process = subprocess.Popen(
        command,
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "DRILL_STATE": str(state),
            "DRILL_CALLS": str(calls),
            "DRILL_FAILURE": failure,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if failure == "cancel":
            deadline = time.monotonic() + 5
            while not state.exists():
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=10)
        expected = 143 if failure == "cancel" else (7 if failure in {"inject", "recover"} else 0)
        assert process.returncode == expected, output
        if failure == "dry_run":
            assert not calls.exists() and not state.exists()
        else:
            assert calls.read_text().splitlines() == ["stop", "up"], output
            assert state.read_text() == ("stopped" if failure == "recover" else "running")
        if failure == "recover":
            assert "manual recovery is required" in output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()
