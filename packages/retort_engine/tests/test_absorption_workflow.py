from __future__ import annotations

import json

from retort_engine.absorption_workflow import absorption_status, absorption_summary, extract_json_from_stdout, is_complete_absorption_stdout_json, truthy


def _complete_payload(status: str = "applied") -> dict[str, object]:
    return {
        "status": status,
        "project": "/tmp/project",
        "summary": "done",
        "changed_files": ["retort_engine/core.py"],
        "gates": [{"ok": True}],
        "gates_passed": True,
        "review_report_path": "/tmp/report.json",
        "employee_results_path": "/tmp/result.json",
    }


def test_extract_json_from_stdout_prefers_last_complete_absorption_payload() -> None:
    first = _complete_payload("noop")
    second = _complete_payload("applied")
    incomplete = {"status": "applied", "changed_files": []}

    parsed = extract_json_from_stdout(f"log {json.dumps(first)}\n{json.dumps(incomplete)}\nfinal {json.dumps(second)}")

    assert parsed["status"] == "applied"
    assert parsed["project"] == "/tmp/project"


def test_extract_json_from_stdout_rejects_incomplete_absorption_payload() -> None:
    assert extract_json_from_stdout(json.dumps({"status": "applied", "changed_files": []})) == {}
    assert is_complete_absorption_stdout_json(_complete_payload()) is True
    assert is_complete_absorption_stdout_json({"status": "applied"}) is False


def test_absorption_status_and_summary_are_fail_closed() -> None:
    tasks = [{"task_id": "one"}]

    assert absorption_status(tasks, {"status": "applied"}) == "absorption_execution_applied"
    assert absorption_status(tasks, {"status": "failed"}) == "absorption_execution_failed"
    assert absorption_status([], {"status": "disabled"}) == "no_external_advantage_found"
    assert "failed" in absorption_summary(tasks, {"status": "failed", "summary": "boom"})


def test_truthy_disables_string_flags() -> None:
    assert truthy("false") is False
    assert truthy("disabled") is False
    assert truthy("yes") is True
