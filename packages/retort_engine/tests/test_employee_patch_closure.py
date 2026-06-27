from __future__ import annotations

import json
import sys
from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.employee_patch_closure import run_employee_patch_closure_case, run_employee_patch_closure_suite
from retort_engine.employee_runtime_worker import write_employee_runtime_results
from retort_engine.service import RetortService


def test_employee_patch_closure_applies_patch_and_passes_gate(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("def value():\n    return 'old'\n", encoding="utf-8")

    result = run_employee_patch_closure_case(
        tmp_path,
        target_file="module.py",
        replacement="def value():\n    return 'new'\n",
        expected_text="return 'new'",
        gate_commands=[[sys.executable, "-m", "py_compile", "{target_file}"]],
        run_id="unit-success",
    )

    assert result["status"] == "patch_verified"
    assert result["summary"]["patch_generated"] is True
    assert result["summary"]["patch_applied"] is True
    assert result["summary"]["gates_passed"] is True
    assert result["summary"]["retained_change"] is True
    assert target.read_text(encoding="utf-8") == "def value():\n    return 'new'\n"
    assert Path(result["evidence"]["patch_path"]).is_file()


def test_employee_patch_closure_rolls_back_when_gate_fails(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    original = "def value():\n    return 'old'\n"
    target.write_text(original, encoding="utf-8")

    result = run_employee_patch_closure_case(
        tmp_path,
        target_file=target,
        replacement="def value(:\n    return 'broken'\n",
        expected_text="broken",
        gate_commands=[[sys.executable, "-m", "py_compile", "{target_file}"]],
        run_id="unit-rollback",
    )

    assert result["status"] == "patch_rolled_back"
    assert result["summary"]["gates_passed"] is False
    assert result["summary"]["rollback_verified"] is True
    assert result["rollback"]["verified"] is True
    assert result["changed_files"] == []
    assert target.read_text(encoding="utf-8") == original


def test_employee_patch_closure_suite_records_success_and_rollback(tmp_path: Path) -> None:
    output = tmp_path / "docs" / "retort_employee_patch_closure.json"

    result = run_employee_patch_closure_suite(tmp_path, output=output, run_id="suite-unit")

    assert result["status"] == "ready"
    assert result["summary"]["success_case_verified"] is True
    assert result["summary"]["failure_case_rolled_back"] is True
    assert result["summary"]["patch_generated_count"] == 2
    assert result["summary"]["patch_applied_count"] == 2
    assert result["summary"]["gate_passed_count"] == 1
    assert result["summary"]["rollback_verified_count"] == 1
    assert output.is_file()
    assert validate_contract("employee_patch_closure_result", result)["valid"] is True


def test_employee_runtime_worker_embeds_patch_closure_evidence(tmp_path: Path) -> None:
    payload = {
        "run_id": "worker-patch-unit",
        "source": "unit",
        "tasks": [{"task_id": "task-1", "dimension": "feedback_loop_closure"}],
        "gates_passed": True,
        "changed_files": ["retort_engine/employee_patch_closure.py"],
        "review_report_path": str(tmp_path / "review.json"),
        "diff_text": "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -0,0 +1 @@\n+token = 'secret'\n",
        "project": str(tmp_path),
        "patch_closure": {"enabled": True, "project": str(tmp_path)},
        "output_path": str(tmp_path / ".retort" / "employee_results" / "worker.json"),
    }
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = write_employee_runtime_results(payload_file)

    patch = result["runtime_evidence"]["employee_patch_closure"]
    assert patch["status"] == "ready"
    assert patch["summary"]["success_case_verified"] is True
    assert patch["summary"]["failure_case_rolled_back"] is True
    assert result["results"][0]["status"] == "completed"
    assert any("employee_patch_closure_status=ready" in item for item in result["results"][0]["evidence"])


def test_service_exposes_employee_patch_closure(tmp_path: Path) -> None:
    result = RetortService().employee_patch_closure({"project": str(tmp_path)})

    assert result["status"] == "ready"
    assert result["summary"]["success_case_verified"] is True
    assert result["summary"]["failure_case_rolled_back"] is True
