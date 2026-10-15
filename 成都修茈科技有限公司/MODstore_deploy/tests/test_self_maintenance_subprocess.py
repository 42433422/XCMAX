"""Real subprocess regressions for deadlines, output bounds and child cleanup."""

from __future__ import annotations

import os
import sys
import time

import pytest

from modstore_server.self_maintenance_subprocess import run_cmd_excerpt


@pytest.mark.parametrize("prefix", ["", "print('partial', flush=True);"])
def test_deadline_covers_silent_and_partial_output(prefix):
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        run_cmd_excerpt([sys.executable, "-c", f"import time;{prefix}time.sleep(3)"], timeout=0.2)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_truncation_drains_without_masking_natural_exit(exit_code):
    args = [
        sys.executable,
        "-c",
        f"import sys;sys.stdout.write('中' * 100000);sys.stdout.flush();sys.exit({exit_code})",
    ]
    if exit_code:
        with pytest.raises(RuntimeError, match=rf"command failed \({exit_code}\)"):
            run_cmd_excerpt(args, max_chars=127)
    else:
        assert run_cmd_excerpt(args, max_chars=127) == "中" * 127


def test_continuing_producer_stops_after_excerpt():
    started = time.monotonic()
    out = run_cmd_excerpt(
        [
            sys.executable,
            "-c",
            "import sys\nwhile True: sys.stdout.write('x' * 8192);sys.stdout.flush()",
        ],
        max_chars=123,
        timeout=10,
    )
    assert out == "x" * 123
    assert time.monotonic() - started < 3


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group lifecycle")
def test_timeout_removes_descendant_holding_stdout(tmp_path):
    marker = tmp_path / "escaped-child"
    child = f"import time;from pathlib import Path;time.sleep(0.8);Path({str(marker)!r}).touch()"
    script = f"import subprocess,sys;subprocess.Popen([sys.executable,'-c',{child!r}])"
    with pytest.raises(RuntimeError, match="timed out"):
        run_cmd_excerpt([sys.executable, "-c", script], timeout=0.2)
    time.sleep(0.9)
    assert not marker.exists()


def test_invalid_timeout_does_not_start_command(tmp_path):
    marker = tmp_path / "started"
    with pytest.raises(ValueError, match="positive"):
        run_cmd_excerpt([sys.executable, "-c", f"open({str(marker)!r},'w').close()"], timeout=0)
    assert not marker.exists()
