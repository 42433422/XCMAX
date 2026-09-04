from __future__ import annotations

import json

from cryptography.fernet import Fernet

import retort_engine.cli as cli_module
from retort_engine.cli import _print_public_json, _print_public_status, _public_status
from retort_engine.secure_artifacts import read_private_json


def test_public_json_receipt_does_not_emit_private_execution_evidence(capsys) -> None:
    private_path = "/private/customer/project/secret.py"
    result = {
        "status": "ready",
        "project": private_path,
        "summary": {"worker_pid": 4242},
        "evidence": {"token": "must-not-print"},
    }

    _print_public_json(result)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload == {
        "schema": "retort.cli.public_receipt/v1",
        "status": "ready",
        "details": "sensitive execution evidence omitted from terminal output",
    }
    assert private_path not in output
    assert "must-not-print" not in output
    assert "4242" not in output


def test_public_text_status_uses_fixed_vocabulary(capsys) -> None:
    result = {"status": "private-status-/customer/path"}

    _print_public_status("Retort operation", result)

    output = capsys.readouterr().out
    assert output == (
        "Retort operation: not_ready\n"
        "Detailed execution evidence is omitted from terminal output.\n"
    )
    assert "customer" not in output
    assert _public_status("applied") == "applied"


def test_scheduler_stress_output_is_encrypted(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "scheduler-result.json"
    private_result = {
        "status": "ready",
        "project": "/private/customer/project",
        "evidence": {"worker": "private"},
    }
    monkeypatch.setenv(
        "RETORT_ARTIFACT_MASTER_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(
        cli_module,
        "run_employee_scheduler_stress",
        lambda *args, **kwargs: private_result,
    )

    exit_code = cli_module.main(
        [
            "employee-scheduler-stress",
            "--project",
            str(tmp_path),
            "--rounds",
            "1",
            "--tasks-per-round",
            "1",
            "--workers-per-round",
            "1",
            "--output",
            str(output),
            "--json",
        ]
    )

    assert exit_code == 0
    assert read_private_json(output, allow_legacy=False) == private_result
    assert "/private/customer/project" not in output.read_text(encoding="utf-8")
    assert "private" not in capsys.readouterr().out
