import json
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


def test_start_reuses_owner_created_customer_work_order(tmp_path, monkeypatch):
    signal = {
        "work_order_id": BASE["wo"],
        "user_id": 41,
        "ticket_id": 9,
        "ticket_no": "CS-9",
        "support_bundle_sha256": "a" * 64,
    }
    signal_path = tmp_path / "signal.json"
    signal_path.write_text(json.dumps(signal), encoding="utf-8")
    monkeypatch.setattr(
        loop,
        "get_work_order",
        lambda _wo: {
            "wo_id": BASE["wo"],
            "source": "client_ai_product_issue",
            "status": "candidate",
            "context": {"customer_reported": True, "customer_user_id": 41},
        },
    )
    transitions = []
    receipts = []
    monkeypatch.setattr(
        loop,
        "record_transition",
        lambda wo, state, **kw: transitions.append((wo, state, kw)) or {"ok": True},
    )
    monkeypatch.setattr(loop, "_receipt", lambda *args, **kw: receipts.append((args, kw)))
    assert loop.cmd_start(Namespace(signal=str(signal_path))) == 0
    assert len(transitions) == 1 and transitions[0][0:2] == (BASE["wo"], "routed")
    assert [item[0][1] for item in receipts] == ["intake", "evidence"]
