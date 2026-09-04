from __future__ import annotations

import json

from retort_engine.cli import _print_public_json, _print_public_status, _public_status


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
