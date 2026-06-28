from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.quality_gate_bundle import run_quality_gate_bundle
from retort_engine.service import RetortService


def test_quality_gate_bundle_runs_lint_pytest_and_contracts(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], root: Path) -> dict[str, object]:
        calls.append(command)
        assert root == tmp_path.resolve()
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    result = run_quality_gate_bundle(tmp_path, python_executable="python", runner=runner)

    assert result["status"] == "ready"
    assert result["summary"]["all_gates_passed"] is True
    assert result["summary"]["lint_passed"] is True
    assert result["summary"]["pytest_passed"] is True
    assert result["summary"]["contract_passed"] is True
    assert result["summary"]["single_command_surface"] is True
    assert [gate["name"] for gate in result["gates"]] == ["lint", "pytest", "contract"]
    assert calls == [["python", "-m", "ruff", "check", "."], ["python", "-m", "pytest", "tests", "-q"]]
    assert validate_contract("quality_gate_bundle_result", result)["valid"] is True


def test_quality_gate_bundle_fails_when_a_gate_fails(tmp_path: Path) -> None:
    def runner(command: list[str], root: Path) -> dict[str, object]:
        if "ruff" in command:
            return {"returncode": 1, "stdout": "", "stderr": "lint failed"}
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    result = run_quality_gate_bundle(tmp_path, python_executable="python", runner=runner)

    assert result["status"] == "failed"
    assert result["summary"]["all_gates_passed"] is False
    assert result["summary"]["lint_passed"] is False
    assert result["evidence"]["failure_names"] == ["lint"]


def test_quality_gate_bundle_writes_report_and_service_exposes_it(tmp_path: Path) -> None:
    def runner(command: list[str], root: Path) -> dict[str, object]:
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    output = tmp_path / "docs" / "quality.json"
    result = run_quality_gate_bundle(tmp_path, output=output, python_executable="python", runner=runner)
    service_result = RetortService().quality_gate_bundle({"project": str(tmp_path)})

    assert output.is_file()
    assert result["status"] == "ready"
    assert service_result["summary"]["contract_passed"] is True
