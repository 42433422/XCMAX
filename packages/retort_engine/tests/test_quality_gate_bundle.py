from __future__ import annotations

from pathlib import Path

from retort_engine.contracts import validate_contract
from retort_engine.quality_gate_bundle import run_quality_gate_bundle
from retort_engine.service import RetortService


def test_quality_gate_bundle_runs_lint_pytest_and_contracts(tmp_path: Path) -> None:
    _write_density_fixture(tmp_path, source_lines=5, test_lines=4)
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
    assert result["summary"]["test_density_passed"] is True
    assert result["summary"]["test_to_source_ratio"] == 0.8
    assert result["summary"]["test_density_target_met"] is True
    assert result["summary"]["test_density_missing_lines_to_target"] == 0
    assert result["summary"]["contract_passed"] is True
    assert result["summary"]["single_command_surface"] is True
    assert [gate["name"] for gate in result["gates"]] == ["lint", "pytest", "test_density", "contract"]
    assert calls == [["python", "-m", "ruff", "check", "."], ["python", "-m", "pytest", "tests", "-q"]]
    assert validate_contract("quality_gate_bundle_result", result)["valid"] is True


def test_quality_gate_bundle_fails_when_a_gate_fails(tmp_path: Path) -> None:
    _write_density_fixture(tmp_path, source_lines=5, test_lines=4)

    def runner(command: list[str], root: Path) -> dict[str, object]:
        if "ruff" in command:
            return {"returncode": 1, "stdout": "", "stderr": "lint failed"}
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    result = run_quality_gate_bundle(tmp_path, python_executable="python", runner=runner)

    assert result["status"] == "failed"
    assert result["summary"]["all_gates_passed"] is False
    assert result["summary"]["lint_passed"] is False
    assert result["evidence"]["failure_names"] == ["lint"]


def test_quality_gate_bundle_reports_density_target_gap(tmp_path: Path) -> None:
    _write_density_fixture(tmp_path, source_lines=10, test_lines=4)

    def runner(command: list[str], root: Path) -> dict[str, object]:
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    result = run_quality_gate_bundle(tmp_path, python_executable="python", runner=runner)

    density_gate = next(gate for gate in result["gates"] if gate["name"] == "test_density")
    assert result["status"] == "failed"
    assert result["summary"]["test_density_passed"] is False
    assert result["summary"]["test_density_target_met"] is False
    assert result["summary"]["test_to_source_ratio"] == 0.4
    assert result["summary"]["test_density_missing_lines_to_target"] == 4
    assert density_gate["ok"] is False
    assert density_gate["target_met"] is False


def test_quality_gate_bundle_blocks_below_density_floor(tmp_path: Path) -> None:
    _write_density_fixture(tmp_path, source_lines=10, test_lines=3)

    def runner(command: list[str], root: Path) -> dict[str, object]:
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    result = run_quality_gate_bundle(tmp_path, python_executable="python", runner=runner)

    assert result["status"] == "failed"
    assert result["summary"]["all_gates_passed"] is False
    assert result["summary"]["test_density_passed"] is False
    assert result["evidence"]["failure_names"] == ["test_density"]


def test_quality_gate_bundle_writes_report_and_service_exposes_it(tmp_path: Path) -> None:
    _write_density_fixture(tmp_path, source_lines=5, test_lines=4)

    def runner(command: list[str], root: Path) -> dict[str, object]:
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    output = tmp_path / "docs" / "quality.json"
    result = run_quality_gate_bundle(tmp_path, output=output, python_executable="python", runner=runner)
    service_result = RetortService().quality_gate_bundle({"project": str(tmp_path)})

    assert output.is_file()
    assert result["status"] == "ready"
    assert service_result["summary"]["contract_passed"] is True


def _write_density_fixture(root: Path, *, source_lines: int, test_lines: int) -> None:
    package = root / "retort_engine"
    tests = root / "tests"
    package.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    (package / "feature.py").write_text("\n".join(f"VALUE_{index} = {index}" for index in range(source_lines)), encoding="utf-8")
    (tests / "test_feature.py").write_text("\n".join(f"assert {index} == {index}" for index in range(test_lines)), encoding="utf-8")
