from __future__ import annotations

import importlib.util
import subprocess
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "self_heal_loop.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("self_heal_loop_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(**overrides: object) -> Namespace:
    values = {
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
    values.update(overrides)
    return Namespace(**values)


def _recording(module: ModuleType, tmp_path: Path) -> list[tuple[str, str, dict[str, object]]]:
    records: list[tuple[str, str, dict[str, object]]] = []
    module._LOOP_DIR = tmp_path
    module.gate_receipts = lambda _wo: {"diagnosis": {"gate_status": "DIAGNOSED"}}
    module.record_gate = lambda _wo, gate, status, **kwargs: (
        records.append((gate, status, kwargs)) or {"ok": True}
    )
    return records


def test_unrelated_failure_cannot_be_recorded_as_red(tmp_path: Path) -> None:
    module = _module()
    records = _recording(module, tmp_path)
    with patch.object(
        module.subprocess,
        "run",
        return_value=subprocess.CompletedProcess("pytest", 1, "ModuleNotFoundError", ""),
    ):
        assert module.cmd_run(_args()) == 1
    assert records[0][1] == "FAILED"


def test_expected_failure_signature_is_required_for_red(tmp_path: Path) -> None:
    module = _module()
    records = _recording(module, tmp_path)
    with patch.object(
        module.subprocess,
        "run",
        return_value=subprocess.CompletedProcess("pytest", 1, "expected failure signature", ""),
    ):
        assert module.cmd_run(_args()) == 0
    assert records[0][1] == "RED"


def test_fix_green_must_repeat_red_command_and_directory(tmp_path: Path) -> None:
    module = _module()
    _recording(module, tmp_path)
    module.gate_receipts = lambda _wo: {
        "repro": {
            "gate_status": "RED",
            "evidence": {
                "command": "pytest -q tests/test_regression.py",
                "cwd": str(SCRIPT.parents[2]),
            },
        }
    }
    with patch.object(module.subprocess, "run") as run:
        with pytest.raises(SystemExit, match="相同的命令和工作目录"):
            module.cmd_run(
                _args(stage="fix_green", expected_signature="", cmd="pytest -q other.py")
            )
    run.assert_not_called()


@pytest.mark.parametrize(
    "option", ("--status", "--fail-status", "--expect-exit", "--expect-nonzero")
)
def test_outcome_override_options_are_not_supported(option: str) -> None:
    module = _module()
    with pytest.raises(SystemExit) as raised:
        module.main(["run", "evidence", "--wo", "WO-123456789abc", "--cmd", "true", option])
    assert raised.value.code == 2
