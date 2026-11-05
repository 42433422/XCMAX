import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/dev"))
import self_heal_loop as loop  # noqa: E402

BASE = {
    "wo": "WO-123456789abc",
    "stage": "repro_red",
    "cmd": "pytest -q tests/test_regression.py",
    "cwd": "",
    "timeout": 10,
    "expected_signature": "expected failure signature",
    "note": "",
    "artifact_sha256": "",
    "release_sha": "",
}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    receipts = {"diagnosis": {"gate_status": "DIAGNOSED"}}
    monkeypatch.setattr(loop, "_LOOP_DIR", tmp_path)
    monkeypatch.setattr(loop, "gate_receipts", lambda _: receipts)
    monkeypatch.setattr(loop, "record_gate", lambda *_, **__: {"ok": True})
    return receipts


def args(**changes):
    return Namespace(**(BASE | changes))


@pytest.mark.parametrize("output", ["other", "expected failure signature"])
def test_red_requires_signature(setup, output):
    with patch.object(
        loop.subprocess, "run", return_value=subprocess.CompletedProcess("pytest", 1, output, "")
    ):
        assert loop.cmd_run(args()) == (output != "expected failure signature")


def test_green_repeats_red_command_and_directory(setup):
    setup["repro"] = {
        "gate_status": "RED",
        "evidence": {"command": BASE["cmd"], "cwd": str(loop._FHD_ROOT)},
    }
    with (
        patch.object(loop.subprocess, "run") as run,
        pytest.raises(SystemExit, match="相同的命令和工作目录"),
    ):
        loop.cmd_run(args(stage="fix_green", expected_signature="", cmd="pytest -q other.py"))
    run.assert_not_called()
