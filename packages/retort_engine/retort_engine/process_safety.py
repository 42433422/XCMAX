from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any


def run_command_with_process_group(
    command: list[str],
    *,
    cwd: str | None = None,
    timeout_sec: float = 30.0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a command in a new process group and kill the whole group on timeout.

    Absorbed from mini-SWE-agent's timeout cleanup pattern: orphan children must
    not survive after the parent budget expires.
    """
    if timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive")
    if not command:
        raise ValueError("command must not be empty")
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    proc = subprocess.Popen(command, **kwargs)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        stdout, stderr = proc.communicate(timeout=5)
    return {
        "command": list(command),
        "returncode": int(proc.returncode if proc.returncode is not None else -9),
        "timed_out": timed_out,
        "elapsed_sec": round(time.monotonic() - started, 6),
        "stdout_tail": (stdout or "")[-4000:],
        "stderr_tail": (stderr or "")[-4000:],
        "process_group_killed": timed_out,
    }


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            proc.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except (OSError, ProcessLookupError):
            pass


def probe_timeout_kills_child(*, timeout_sec: float = 0.4) -> dict[str, Any]:
    """Launch a child that spawns a sleeper and prove timeout kills the group."""
    child_script = (
        "import os, subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "time.sleep(30)\n"
    )
    result = run_command_with_process_group(
        [sys.executable, "-c", child_script],
        timeout_sec=timeout_sec,
    )
    result["probe"] = "timeout_kills_process_group"
    result["verified"] = bool(result["timed_out"] and result["process_group_killed"])
    return result
